"""
NIS2 Audit Agent — Claude-powered automated security audit
"""
import os
import json
import subprocess
import shutil
from datetime import datetime

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from models import db_execute, db_query

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAX_ITERATIONS    = 20


def _log(order_id: int, level: str, message: str):
    db_execute(
        "INSERT INTO audit_logs (order_id,level,message,created_at) VALUES (?,?,?,?)",
        (order_id, level, message, datetime.now().isoformat())
    )


def _add_finding(order_id: int, title: str, description: str, severity: str,
                 recommendation: str = "", cvss: str = "", dsgvo_article: str = "",
                 target: str = ""):
    RANK = {"critical": 1, "high": 2, "medium": 3, "low": 4, "info": 5}
    rank = RANK.get(severity.lower(), 5)
    db_execute(
        """INSERT INTO findings
           (order_id,title,description,severity,severity_rank,target,recommendation,cvss,dsgvo_article,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (order_id, title, description, severity, rank, target,
         recommendation, cvss, dsgvo_article, datetime.now().isoformat())
    )


def _run_cmd(cmd: list, timeout: int = 60) -> str:
    """Run a shell command and return stdout+stderr, truncated."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        out = (result.stdout + result.stderr).strip()
        return out[:4000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return f"(timeout after {timeout}s)"
    except FileNotFoundError:
        return f"(tool not found: {cmd[0]})"
    except Exception as e:
        return f"(error: {e})"


def _tool_nmap(target: str) -> str:
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    return _run_cmd(["nmap", "-sV", "--open", "-T4", "-p", "21,22,23,25,53,80,443,3306,8080,8443", host], timeout=60)


def _tool_nuclei(target: str) -> str:
    if not shutil.which("nuclei"):
        return "(nuclei not installed)"
    return _run_cmd(["nuclei", "-u", target, "-severity", "critical,high,medium",
                     "-silent", "-no-color", "-timeout", "10"], timeout=120)


def _tool_httpx(target: str) -> str:
    if not shutil.which("httpx"):
        return "(httpx not installed)"
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    return _run_cmd(["httpx", "-u", host, "-title", "-status-code", "-tech-detect",
                     "-follow-redirects", "-silent"], timeout=30)


def _tool_subfinder(target: str) -> str:
    if not shutil.which("subfinder"):
        return "(subfinder not installed)"
    host = target.replace("https://", "").replace("http://", "").split("/")[0]
    parts = host.split(".")
    domain = ".".join(parts[-2:]) if len(parts) >= 2 else host
    return _run_cmd(["subfinder", "-d", domain, "-silent", "-t", "20"], timeout=60)


TOOLS = {
    "nmap":      {"fn": _tool_nmap,      "desc": "Port scan with service detection"},
    "nuclei":    {"fn": _tool_nuclei,    "desc": "Vulnerability scan (CVE, misconfigs)"},
    "httpx":     {"fn": _tool_httpx,     "desc": "HTTP probe: title, status, tech stack"},
    "subfinder": {"fn": _tool_subfinder, "desc": "Subdomain enumeration"},
}

SYSTEM_PROMPT = """You are an expert cybersecurity auditor specializing in NIS2 and DSGVO compliance for German businesses.
You have access to security tools and must conduct a thorough audit of the target.

Your goals:
1. Run relevant security tools to find vulnerabilities
2. Analyze results and identify NIS2/DSGVO compliance issues
3. Add findings using add_finding for each discovered issue
4. Log progress using log_message
5. Complete within {max_iter} iterations

For each finding set appropriate severity: critical/high/medium/low/info
Map findings to DSGVO articles (Art. 32, Art. 25, Art. 33 etc.) and NIS2 (§30 BSIG)

When done, call finish_audit.
"""

TOOLS_SPEC = [
    {
        "name": "run_tool",
        "description": "Run a security scanning tool against the target",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool": {
                    "type": "string",
                    "enum": list(TOOLS.keys()),
                    "description": "Tool to run"
                },
                "target": {
                    "type": "string",
                    "description": "Target URL or domain"
                }
            },
            "required": ["tool", "target"]
        }
    },
    {
        "name": "add_finding",
        "description": "Add a security finding to the audit report",
        "input_schema": {
            "type": "object",
            "properties": {
                "title":          {"type": "string"},
                "description":    {"type": "string"},
                "severity":       {"type": "string", "enum": ["critical","high","medium","low","info"]},
                "recommendation": {"type": "string"},
                "cvss":           {"type": "string"},
                "dsgvo_article":  {"type": "string"},
                "target":         {"type": "string"}
            },
            "required": ["title", "description", "severity"]
        }
    },
    {
        "name": "log_message",
        "description": "Log a status message to the audit log",
        "input_schema": {
            "type": "object",
            "properties": {
                "level":   {"type": "string", "enum": ["INFO","CMD","FINDING","AGENT","ERROR"]},
                "message": {"type": "string"}
            },
            "required": ["level", "message"]
        }
    },
    {
        "name": "finish_audit",
        "description": "Mark the audit as complete",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Brief summary of findings"}
            },
            "required": ["summary"]
        }
    }
]


def run_audit_agent(order_id: int, target: str, company: str):
    """Main entry point — runs the Claude-powered audit agent."""
    _log(order_id, "INFO", f"Audit gestartet: {target} ({company})")

    if not HAS_ANTHROPIC:
        _log(order_id, "ERROR", "anthropic library not installed")
        db_execute("UPDATE orders SET status='failed',updated_at=? WHERE id=?",
                   (datetime.now().isoformat(), order_id))
        return

    if not ANTHROPIC_API_KEY:
        _log(order_id, "ERROR", "ANTHROPIC_API_KEY nicht gesetzt — KI-Audit nicht möglich")
        db_execute("UPDATE orders SET status='failed',updated_at=? WHERE id=?",
                   (datetime.now().isoformat(), order_id))
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    messages = [
        {
            "role": "user",
            "content": (
                f"Conduct a NIS2/DSGVO security audit for company: {company}\n"
                f"Target URL: {target}\n\n"
                f"Start with httpx to get basic info, then run nmap for ports, "
                f"subfinder for subdomains, and nuclei for vulnerabilities. "
                f"Add findings for every issue you discover."
            )
        }
    ]

    finished = False
    for iteration in range(MAX_ITERATIONS):
        _log(order_id, "AGENT", f"Iteration {iteration + 1}/{MAX_ITERATIONS}")

        try:
            response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                system=SYSTEM_PROMPT.format(max_iter=MAX_ITERATIONS),
                tools=TOOLS_SPEC,
                messages=messages,
            )
        except Exception as e:
            _log(order_id, "ERROR", f"Claude API Fehler: {e}")
            break

        # Collect assistant message
        assistant_content = []
        tool_results = []

        for block in response.content:
            assistant_content.append(block)

            if block.type == "text":
                _log(order_id, "AGENT", block.text[:500])

            elif block.type == "tool_use":
                tool_name  = block.name
                tool_input = block.input
                tool_use_id = block.id

                _log(order_id, "CMD", f"{tool_name}: {json.dumps(tool_input)[:200]}")

                # Execute tool
                if tool_name == "run_tool":
                    t = tool_input.get("tool")
                    tgt = tool_input.get("target", target)
                    if t in TOOLS:
                        output = TOOLS[t]["fn"](tgt)
                        _log(order_id, "OUT", output[:300])
                    else:
                        output = f"Unknown tool: {t}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": output
                    })

                elif tool_name == "add_finding":
                    _add_finding(
                        order_id,
                        title          = tool_input.get("title",""),
                        description    = tool_input.get("description",""),
                        severity       = tool_input.get("severity","info"),
                        recommendation = tool_input.get("recommendation",""),
                        cvss           = tool_input.get("cvss",""),
                        dsgvo_article  = tool_input.get("dsgvo_article",""),
                        target         = tool_input.get("target", target),
                    )
                    _log(order_id, "FINDING", f"[{tool_input.get('severity','info').upper()}] {tool_input.get('title','')}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": "Finding added"
                    })

                elif tool_name == "log_message":
                    _log(order_id,
                         tool_input.get("level","INFO"),
                         tool_input.get("message",""))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": "Logged"
                    })

                elif tool_name == "finish_audit":
                    summary = tool_input.get("summary","")
                    _log(order_id, "INFO", f"AUDIT ABGESCHLOSSEN: {summary}")
                    db_execute("UPDATE orders SET status='done',updated_at=? WHERE id=?",
                               (datetime.now().isoformat(), order_id))
                    finished = True
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": "Audit finished"
                    })

        # Append assistant message and tool results to conversation
        messages.append({"role": "assistant", "content": assistant_content})
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        if finished or response.stop_reason == "end_turn":
            break

    if not finished:
        _log(order_id, "INFO", "AUDIT ABGESCHLOSSEN (max. Iterationen erreicht)")
        db_execute("UPDATE orders SET status='done',updated_at=? WHERE id=?",
                   (datetime.now().isoformat(), order_id))
