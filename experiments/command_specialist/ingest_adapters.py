"""Read recorded tool events. Never evaluate transcript text or replay commands.

All normalized rows remain private. Context is a lead for review, not a gold intent.
Unknown formats stay accounted for in the source snapshot and disposition counters.
"""
from __future__ import annotations

import base64
import collections
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(x.get("text", "") for x in value
                         if isinstance(x, dict) and isinstance(x.get("text"), str))
    return ""


def object_value(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            pass
    return {}


def command_value(tool, arguments):
    """Only explicit shell-tool inputs. JS orchestration is deliberately not evaluated."""
    name = str(tool).split(".")[-1].split("__")[-1].lower()
    if name not in {"exec_command", "shell_command", "shell", "bash", "powershell",
                    "run_terminal_cmd", "run_terminal_command", "run_shell_command", "oc_bash"}:
        return None
    for key in ("cmd", "command", "command_line"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
            return value
    return None


def result_value(value):
    obj = object_value(value)
    exit_code = obj.get("exit_code", obj.get("exitCode"))
    # bool is an int in Python; it is not an exit code in this schema.
    exit_code = exit_code if type(exit_code) is int else None
    for key in ("output", "stdout", "aggregated_output", "content", "error"):
        if key in obj:
            output = text_content(obj[key])
            if output or obj[key] == "":
                if key == "stdout" and isinstance(obj.get("stderr"), str):
                    output += "\n" + obj["stderr"]
                return output, exit_code
    return text_content(value) or (json.dumps(value, ensure_ascii=False) if value is not None else ""), exit_code


class Adapter:
    def __init__(self, kind, source_key):
        self.kind = kind
        self.source_key = source_key
        self.session = source_key
        self.cwd = None
        self.context = ""
        self.context_pointer = None
        self.context_truncated = False
        self.calls = {}
        self.results = {}
        self.native = {}
        self.emitted = []
        self.counts = collections.Counter()
        self.message_roles = {}
        self.session_contexts = {}
        self.session_parents = {}

    def context_set(self, text, pointer):
        self.context = text[:8000]
        self.context_truncated = len(text) > 8000
        self.context_pointer = pointer

    def switch_session(self, session):
        if session != self.session:
            self.session_contexts[self.session] = (self.context, self.context_pointer, self.context_truncated)
            self.session = str(session)
            self.context, self.context_pointer, self.context_truncated = self.session_contexts.get(
                self.session, ("", None, False))
            self.cwd = None

    def call(self, call_id, tool, args, pointer, timestamp=None):
        args = object_value(args)
        command = command_value(tool, args)
        if command is None:
            self.counts["unsupported_tool:" + str(tool)] += 1
            return False
        key = (self.session, str(call_id or pointer))
        row = {"session": self.session, "call_id": str(call_id or pointer), "command": command,
               "tool": str(tool), "cwd": args.get("workdir", args.get("cwd", self.cwd)),
               "shell": args.get("shell"), "timestamp": timestamp,
               "call_pointer": pointer, "request_context": self.context,
               "context_pointer": self.context_pointer, "context_truncated": self.context_truncated,
               "context_association": "preceding_user_message_unverified" if self.context else "missing",
               "description": args.get("description", args.get("justification", ""))}
        if key in self.calls:
            self.counts["duplicate_call_events"] += 1
            if self.calls[key]["command"] == command:
                return True
            else:
                # Preserve conflicting IDs, but never silently pair their results.
                row["call_id_conflict"] = True
                row["call_id"] += ":conflict:" + digest(pointer)[:12]
                key = (self.session, row["call_id"])
        self.calls[key] = row
        return True

    def result(self, call_id, value, pointer, **extra):
        key = (self.session, str(call_id))
        output, code = result_value(value)
        result = {"output": output, "exit_code": code, "result_pointer": pointer,
                  "result_present": True, **extra}
        if key in self.results and all(self.results[key].get(k) == result.get(k) for k in ("output", "exit_code")):
            self.counts["duplicate_result_events"] += 1
            return
        if key in self.results:
            # Multiple output chunks are retained; no fabricated completion status.
            previous = self.results[key]
            result["output"] = previous["output"] + "\n" + output
            result["additional_result_pointers"] = previous.get("additional_result_pointers", []) + [previous["result_pointer"]]
        self.results[key] = result

    def consume(self, row, pointer):
        if self.kind in {"codex", "claude", "legacy"}:
            return getattr(self, self.kind)(row, pointer)
        if not isinstance(row.get("row"), dict):
            return "unsupported_record"
        data = row["row"].get("data")
        if isinstance(data, dict) and "base64" in data:
            try:
                data = base64.b64decode(data["base64"], validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return "non_json_blob"
        if row.get("table") == "blobs":
            try:
                obj = json.loads(data)
            except (ValueError, TypeError):
                return "non_json_blob"
            return self.cursor(obj, pointer) if isinstance(obj, dict) else "non_object_blob"
        if row.get("table") in {"session", "session_v2"}:
            source = row["row"]
            self.session_parents[str(source.get("id"))] = [str(source[k]) for k in ("parent_id", "fork_session_id") if source.get(k)]
            return "metadata"
        if row.get("table") in {"part", "message", "session_message"}:
            try:
                obj = json.loads(data)
            except (ValueError, TypeError):
                return "malformed_embedded_json"
            if not isinstance(obj, dict):
                return "non_object_record"
            return self.opencode(row["table"], row["row"], obj, pointer)
        return "metadata"

    def codex(self, row, pointer):
        p = row.get("payload")
        if not isinstance(p, dict):
            return "unsupported_record"
        typ = row.get("type")
        if typ == "session_meta":
            self.switch_session(p.get("id") or p.get("session_id") or self.source_key)
            self.cwd = p.get("cwd")
            parents = []
            def collect(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in {"parent_thread_id", "parent_session_id", "forked_from_id"} and isinstance(item, str):
                            parents.append(item)
                        elif isinstance(item, dict):
                            collect(item)
            collect(p.get("source"))
            collect(p.get("thread_source"))
            self.session_parents[self.session] = parents
            return "metadata"
        if typ == "turn_context":
            self.cwd = p.get("cwd", self.cwd)
            return "metadata"
        if typ == "response_item":
            if p.get("type") == "message":
                if p.get("role") == "user":
                    self.context_set(text_content(p.get("content")), pointer)
                return "message"
            if p.get("type") in {"function_call", "custom_tool_call"}:
                ok = self.call(p.get("call_id"), p.get("name"), p.get("arguments", p.get("input")), pointer, row.get("timestamp"))
                return "command_call" if ok else "unsupported_tool_call"
            if p.get("type") in {"function_call_output", "custom_tool_call_output"}:
                self.result(p.get("call_id"), p.get("output"), pointer)
                return "tool_result"
            return "other_response"
        if typ == "event_msg":
            if p.get("type") == "user_message":
                self.context_set(text_content(p.get("message")), pointer)
                return "message"
            item = p.get("item")
            if p.get("type") == "item_completed" and isinstance(item, dict) and item.get("type") == "CommandExecution":
                command = item.get("command")
                if not (isinstance(command, list) and command and all(isinstance(x, str) for x in command)):
                    return "unsupported_command_shape"
                key = (self.session, str(item.get("id") or pointer))
                code = item.get("exit_code")
                native = {"session": self.session, "call_id": key[1], "command": command,
                          "tool": "native_command_execution", "cwd": item.get("cwd", self.cwd),
                          "shell": command[0], "timestamp": row.get("timestamp"),
                          "call_pointer": pointer, "result_pointer": pointer,
                          "request_context": self.context, "context_pointer": self.context_pointer,
                          "context_truncated": self.context_truncated,
                          "context_association": "preceding_user_message_unverified" if self.context else "missing",
                          "output": text_content(item.get("aggregated_output", item.get("formatted_output", ""))),
                          "exit_code": code if type(code) is int else None,
                          "result_present": True, "recorded_status": item.get("status"),
                          "exit_code_origin": "native_event_field"}
                if key in self.native:
                    self.counts["duplicate_native_events"] += 1
                    if any(self.native[key][k] != native[k] for k in ("command", "output", "exit_code")):
                        native["call_id_conflict"] = True
                        native["call_id"] += ":conflict:" + digest(pointer)[:12]
                        key = (self.session, native["call_id"])
                self.native[key] = native
                return "native_command"
            return "other_event"
        return "metadata"

    def claude(self, row, pointer):
        self.switch_session(row.get("sessionId") or self.session)
        self.cwd = row.get("cwd", self.cwd)
        message = row.get("message")
        if not isinstance(message, dict):
            return "metadata"
        content = message.get("content", [])
        if isinstance(content, str):
            if row.get("type") == "user":
                self.context_set(content, pointer)
            return "message"
        if not isinstance(content, list):
            return "unsupported_message_shape"
        if row.get("type") == "user" and not any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content):
            self.context_set(text_content(content), pointer)
        handled = False
        for index, part in enumerate(content):
            if not isinstance(part, dict):
                continue
            where = {**pointer, "part": index}
            if row.get("type") == "assistant" and part.get("type") == "tool_use":
                self.call(part.get("id"), part.get("name"), part.get("input"), where, row.get("timestamp"))
                handled = True
            elif row.get("type") == "user" and part.get("type") == "tool_result":
                self.result(part.get("tool_use_id"), part.get("content"), where,
                            recorded_tool_error=part.get("is_error"))
                handled = True
        return "tool_event_message" if handled else "message"

    def cursor(self, row, pointer):
        # Blob table ordering is not conversation ordering. Do not invent user context.
        content = row.get("content")
        if not isinstance(content, list):
            return "message"
        handled = False
        for index, part in enumerate(content):
            if not isinstance(part, dict):
                continue
            where = {**pointer, "part": index}
            if row.get("role") == "assistant" and part.get("type") == "tool-call":
                self.call(part.get("toolCallId"), part.get("toolName"), part.get("args"), where)
                handled = True
            if row.get("role") == "tool" and part.get("type") == "tool-result":
                self.result(part.get("toolCallId"), part.get("result"), where)
                handled = True
        return "tool_event_message" if handled else "message"

    def opencode(self, table, source, data, pointer):
        self.switch_session(source.get("session_id") or self.session)
        if table == "message":
            self.message_roles[source.get("id")] = data.get("role")
            return "metadata"
        if table == "session_message":
            role = source.get("type")
            if role == "user":
                self.context_set(text_content(data.get("text", data.get("content", ""))), pointer)
                return "message"
            if role != "assistant":
                return "metadata"
            parts = data.get("content", [])
        else:
            role = self.message_roles.get(source.get("message_id"))
            if role == "user" and data.get("type") == "text":
                self.context_set(text_content(data.get("text")), pointer)
            parts = [data]
        handled = False
        for index, part in enumerate(parts if isinstance(parts, list) else []):
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            where = {**pointer, "part": index}
            state = part.get("state") or {}
            if not isinstance(state, dict):
                continue
            key = part.get("callID", part.get("id"))
            self.call(key, part.get("tool", part.get("name")), state.get("input"), where, source.get("time_created"))
            if state.get("status") in {"completed", "error"}:
                value = {"output": state.get("output", state.get("content", state.get("error", "")))}
                metadata = state.get("metadata") or {}
                if isinstance(metadata, dict):
                    value["exit_code"] = metadata.get("exit", metadata.get("exitCode", metadata.get("exit_code")))
                self.result(key, value, where, recorded_status=state.get("status"))
            handled = True
        return "tool_event_message" if handled else "message"

    def legacy(self, row, pointer):
        cmd = row.get("cmd")
        if not isinstance(cmd, str) or not cmd.strip():
            return "missing_command"
        code = row.get("exit")
        self.emitted.append({"session": str(row.get("session") or self.source_key),
                             "call_id": str(pointer["line"]), "command": cmd, "tool": "legacy_extracted",
                             "cwd": None, "shell": None, "timestamp": None,
                             "call_pointer": pointer, "result_pointer": pointer,
                             "request_context": "", "context_pointer": None, "context_truncated": False,
                             "context_association": "missing", "description": row.get("desc") or "",
                             "output": row.get("out") or "", "exit_code": code if type(code) is int else None,
                             "exit_code_origin": "legacy_extractor_unverified",
                             "result_present": bool(row.get("out")), "legacy_hidden_failure": bool(row.get("hidden")),
                             "legacy_dynamic": bool(row.get("dynamic")), "legacy_unmatched": bool(row.get("unmatched")),
                             "source_cap_suspected": len(row.get("out") or "") == 700})
        return "legacy_command"

    def finish(self):
        for key, row in self.calls.items():
            if key in self.native:
                native = self.native[key]
                native["call_pointer"] = row["call_pointer"]
                native["context_pointer"] = row["context_pointer"]
                native["request_context"] = row["request_context"]
                native["context_truncated"] = row["context_truncated"]
                native["context_association"] = row["context_association"]
                self.counts["call_native_pairs"] += 1
                continue
            result = self.results.get(key, {"output": "", "exit_code": None, "result_present": False})
            self.emitted.append({**row, **result})
        self.emitted.extend(self.native.values())
        self.counts["unmatched_result_events"] = len(set(self.results) - set(self.calls) - set(self.native))
        for row in self.emitted:
            row["source_kind"] = self.kind
            row["parent_sessions"] = self.session_parents.get(row["session"], [])
            row["record_id"] = digest([self.kind, row["session"], row["call_id"], row["command"]])
            row["command_sha256"] = digest(row["command"])
            row["output_sha256"] = digest(row["output"])
            row["exit_code_origin"] = row.get("exit_code_origin", "structured_result_field" if row["exit_code"] is not None else "missing")
            row["labels"] = {
                "execution": "unknown" if row["exit_code"] is None else "exit_zero" if row["exit_code"] == 0 else "exit_nonzero",
                "task_correctness": "abstain",
                "source_truncation_marker": bool(re.search(r"tokens truncated|bytes omitted|<truncated", row["output"], re.I)),
                "output_error_keyword": bool(re.search(r"\b(error|failed|exception)\b", row["output"], re.I)),
                "label_basis": "recorded_fields_and_heuristics_v1",
            }
            yield row
