# Author: WangLei
# Email: WangLei1578@outlook.com
# Date: 2026-09-28

import json
import logging
import os
import re
import urllib.request

RULES = [
    ("ip", "HIGH", "知识产权归属", r"知识产权.{0,15}(归|属).{0,8}(供应商|乙方|承包方|服务方).{0,8}(所有|享有|拥有)", "成果知识产权全部归对方，可能导致我方无法继续使用交付成果。", "明确约定项目成果及定制开发成果的知识产权归属，并授予我方持续、不可撤销的使用权。", "项目成果及定制开发成果的知识产权归我方所有；对方背景知识产权归原权利人所有，并授予我方为使用项目成果所需的永久、不可撤销、免费的许可。"),
    ("payment", "HIGH", "付款缺少验收条件", r"(到货|交付|签订合同).{0,12}(支付|付款).{0,8}(全部|全额|100%|百分之百)", "约定交付后全额付款但未见验收前置条件，验收不合格时缺乏付款控制。", "将付款与交付验收合格、收到合规发票挂钩，并保留整改及质保款。", "我方在完成验收并收到合规发票后，按合同约定支付相应款项；验收不合格的，对方应先行整改。"),
    ("liability", "HIGH", "违约责任不对等", r"(我方|甲方).{0,50}(无限|无上限|全部|全额|不设上限).{0,10}(赔偿|责任)|(我方|甲方).{0,50}(赔偿|责任).{0,8}(无限|无上限|不设上限)|对方.{0,20}(不承担|无需承担).{0,10}(责任|赔偿)", "责任分配明显不对等，可能使我方承担无法预估的损失。", "设置双方对等的违约责任和合理责任上限，故意或重大过失除外。", "双方因违约承担对等责任；除故意、重大过失及法律另有规定外，累计赔偿责任以合同总金额为限。"),
    ("force_majeure", "MEDIUM", "不可抗力通知期限缺失", r"不可抗力(?!.*(日内|小时内|通知))", "未约定不可抗力通知时限及证明义务，不利于及时控制损失。", "增加及时书面通知、提供证明及采取减损措施的义务。", "受影响方应在不可抗力发生后五日内书面通知对方，并在合理期限内提供证明及采取必要减损措施。"),
]


def llm_review(text, existing):
    body = json.dumps({"model": os.getenv("LLM_DEFAULT_MODEL", "deepseek-chat"), "temperature": 0, "messages": [{"role": "system", "content": '你是合同风险审查助手。只返回JSON数组，每项包含level(HIGH/MEDIUM/LOW),title,clause_type,original_text,risk_reason,legal_basis,suggestion,suggested_text。证据必须是合同原文。无风险返回[]。'}, {"role": "user", "content": text[:30000]}]}).encode()
    req = urllib.request.Request(os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1/chat/completions"), body, {"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.load(response)
    items = json.loads(data["choices"][0]["message"]["content"])
    output = []
    for item in items if isinstance(items, list) else []:
        quote = str(item.get("original_text", ""))
        pos = text.find(quote)
        if pos < 0 or any(risk["original_text"] == quote for risk in existing):
            continue
        output.append({"level": item.get("level", "MEDIUM") if item.get("level") in {"HIGH", "MEDIUM", "LOW"} else "MEDIUM", "title": str(item.get("title", "合同风险"))[:100], "clause_type": str(item.get("clause_type", "other"))[:50], "original_text": quote, "start": pos, "end": pos + len(quote), "reason": str(item.get("risk_reason", ""))[:1000], "legal_basis": str(item.get("legal_basis", "需法务核验"))[:1000], "suggestion": str(item.get("suggestion", ""))[:1000], "suggested_text": str(item.get("suggested_text", ""))[:2000]})
    return output


def review(text):
    found = []
    for kind, level, title, pattern, reason, suggestion, proposed in RULES:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            found.append({"level": level, "title": title, "clause_type": kind, "original_text": match.group(0), "start": match.start(), "end": match.end(), "reason": reason, "legal_basis": "系统内置合同审查规则；需结合具体交易背景由法务复核。", "suggestion": suggestion, "suggested_text": proposed})
    for match in re.finditer(r"[^。；;\n\f]*(?:保密义务|保密信息)[^。；;\n\f]*[。；;]?", text):
        quote = match.group(0).strip()
        if "保密义务" in quote and not re.search(r"(?:\d+年|\d+个月|永久|终止后)", quote):
            start = text.find(quote, match.start())
            if start >= 0:
                found.append({"level": "MEDIUM", "title": "保密义务期限缺失", "clause_type": "confidentiality", "original_text": quote, "start": start, "end": start + len(quote), "reason": "未明确保密义务的存续期限，可能造成执行争议。", "legal_basis": "系统内置合同审查规则；需结合具体交易背景由法务复核。", "suggestion": "明确保密义务在合同终止后继续有效的期限；商业秘密在其依法构成商业秘密期间持续保护。", "suggested_text": "保密义务自信息披露之日起至合同终止后五年内持续有效；依法构成商业秘密的信息在其商业秘密存续期间持续保密。"})
    if not any(risk["clause_type"] == "payment" for risk in found) and re.search(r"(付款|支付).{0,80}(全部|全额|100%|结清)", text, re.S) and not re.search(r"验收.{0,20}(合格|通过)", text):
        match = re.search(r".{0,30}(?:付款|支付).{0,80}(?:全部|全额|100%|结清).{0,30}", text, re.S)
        if match:
            found.append({"level": "HIGH", "title": "付款前置验收条件缺失", "clause_type": "payment", "original_text": match.group(0).strip(), "start": match.start(), "end": match.end(), "reason": "合同约定支付全部款项，但未明确验收合格这一付款前置条件。", "legal_basis": "系统内置合同审查规则；需结合具体交易背景由法务复核。", "suggestion": "将付款与交付验收合格及收到合规发票挂钩。", "suggested_text": "我方在完成验收并收到合规发票后支付相应款项；验收不合格的，对方应先行整改。"})
    if os.getenv("LLM_REVIEW_ENABLED", "0").lower() in {"1", "true", "yes"} and os.getenv("DEEPSEEK_API_KEY") and text.strip():
        for attempt in range(2):
            try:
                found.extend(llm_review(text, found))
                break
            except Exception as exc:
                if attempt:
                    logging.getLogger(__name__).warning("LLM review unavailable; using rules (%s)", type(exc).__name__)
    return found
