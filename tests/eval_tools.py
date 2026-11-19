"""Замер: какая модель правильно выбирает инструмент и аргументы. Ничего не выполняет — только смотрит первый вызов.

  python tests/eval_tools.py --model qwen3.5:9b --model gpt-oss:20b            # все инструменты разом
  python tests/eval_tools.py --model qwen3.5:9b --grouped                      # только нужная группа инструментов
  python tests/eval_tools.py --url http://192.168.1.50:11434 --model gpt-oss:20b --repeat 3 --json out.json
Показатели: инструмент — верный; аргументы — совпали ожидаемые поля; схема — аргументы прошли проверку реестра;
сек — среднее время шага. Набор — tests/eval_cases.json (допишите свои фразы). Сторонние MCP-серверы не входят."""
import argparse
import ast
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import config      # noqa: E402
import persona     # noqa: E402
import tools       # noqa: E402
from llm import LLM  # noqa: E402


def act_rules():
    """ACT_RULES из brain.py без импорта brain (он тянет интерфейс)."""
    src = open(os.path.join(os.path.dirname(HERE), "brain.py"), encoding="utf-8").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ACT_RULES":
            return ast.literal_eval(node.value)
    return ""


def match(exp, got):
    if isinstance(exp, bool):
        return got is exp or str(got).lower() == str(exp).lower()
    if isinstance(exp, (int, float)):
        try:
            return float(got) == float(exp)
        except (TypeError, ValueError):
            return False
    items = got if isinstance(got, list) else [got]
    return any(str(exp).lower() in str(x).lower() for x in items)


def run_case(llm, cfg, case, model, grouped, rules):
    cfg["tool_groups"] = grouped
    schemas = tools.schemas(cfg, case["say"].lower())
    msgs = [{"role": "system", "content": persona.system_prompt(cfg, [], extra=rules)},
            {"role": "user", "content": case["say"]}]
    t0 = time.time()
    try:
        _, calls = llm.chat_tools(msgs, schemas, model=model)
        err = ""
    except Exception as e:           # noqa: BLE001
        calls, err = [], f"{type(e).__name__}: {e}"
    dt = time.time() - t0
    want = case["tool"]
    name, args = calls[0] if calls else ("None", {})
    ok_tool = name == want
    ok_args = ok_tool and all(k in args and match(v, args[k]) for k, v in case.get("args", {}).items())
    ok_schema = True
    if calls and name in tools.REGISTRY:
        try:
            tools.validate(tools.REGISTRY[name].schema_for(cfg), args)
        except Exception:            # noqa: BLE001
            ok_schema = False
    elif calls:
        ok_schema = False            # выдумал несуществующий инструмент
    return {"say": case["say"], "want": want, "got": name, "args": args, "tool": ok_tool, "args_ok": ok_args,
            "schema": ok_schema, "sec": dt, "offered": len(schemas), "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", required=True)
    ap.add_argument("--url")
    ap.add_argument("--grouped", action="store_true")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--cases", default=os.path.join(HERE, "eval_cases.json"))
    ap.add_argument("--json")
    a = ap.parse_args()
    cfg = config.load()
    if a.url:
        cfg["ollama_url"] = a.url
    cfg["ollama_url_fallback"] = ""
    cfg["kb_folders"] = cfg.get("kb_folders") or ["~/Documents"]
    cfg["log_sources"] = [{"name": "app", "type": "file", "path": "app.log"}]
    cfg["wol_mac"] = "AA:BB:CC:DD:EE:FF"
    cfg["coder_projects"] = {"demo": "."}
    cases = json.load(open(a.cases, encoding="utf-8"))
    llm, rules, report = LLM(cfg), act_rules(), {}
    for model in a.model:
        rows = [run_case(llm, cfg, c, model, a.grouped, rules) for _ in range(a.repeat) for c in cases]
        n = len(rows)
        pct = lambda k: 100 * sum(r[k] for r in rows) / n          # noqa: E731
        print(f"\n== {model} · {'группы' if a.grouped else 'все инструменты'} · предложено инструментов ≈ "
              f"{sum(r['offered'] for r in rows) // n} · {n} прогонов")
        print(f"   инструмент {pct('tool'):.0f}% · аргументы {sum(r['args_ok'] for r in rows if r['want'] != 'None') * 100 // max(1, sum(1 for r in rows if r['want'] != 'None'))}%"
              f" · схема {pct('schema'):.0f}% · {sum(r['sec'] for r in rows) / n:.1f} с на шаг")
        for r in rows:
            if not (r["tool"] and r["args_ok"] and r["schema"]):
                print(f"   ✗ «{r['say']}» → {r['got']} {json.dumps(r['args'], ensure_ascii=False)}"
                      f" (ждали {r['want']}){' ' + r['error'] if r['error'] else ''}")
        report[model] = rows
    if a.json:
        json.dump(report, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
