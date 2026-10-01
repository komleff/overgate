#!/usr/bin/env bash
# Static contracts only: это не доказательство фактического LLM поведения.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
python3 - "$ROOT" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
def case(name, path, *phrases):
    text = (root / path).read_text()
    for phrase in phrases:
        assert phrase in text, f'{name}: missing {phrase!r} in {path}'
    print('PASS static route:', name)
case('complete source PASS_THROUGH; no forced spec', '.agents/PM_ROLE.md', 'PASS_THROUGH', 'новый spec', 'не обязательны', 'CREATE_SPEC')
case('missing WHAT PRODUCT GAP; operator fallback', '.agents/skills/product-gap/SKILL.md', 'PRODUCT GAP', 'Decision required from: оператор', 'не маскировать product choice')
case('technical uncertainty first repo', '.agents/PM_ROLE.md', 'Technical uncertainty сначала исследуй по', 'repo')
case('planner does not choose WHAT', '.agents/PL_ROLE.md', 'PRODUCT GAP', 'не выбирай product behaviour')
case('unknown diagnosis RED evidence GREEN/limit', '.agents/skills/diagnose/SKILL.md', 'RED confirmed', 'Discriminating evidence', 'GREEN', 'REPRODUCTION LIMIT')
case('known cause does not force heavy diagnosis', '.agents/DEV_ROLE.md', 'Известная простая причина не требует')
case('QA ambiguity NOT RUN', '.agents/QA_ROLE.md', 'Result: NOT RUN', 'Reason: unresolved product/contract ambiguity', 'Новый global verdict enum не вводи')
for role in ('PM','SV','PL','DEV','QA','RV'):
    case('completed work without handoff '+role, f'.agents/{role}_ROLE.md', 'После завершённой работы handoff не создавай')
case('handoff preserves reviewer mode', '.agents/skills/handoff/SKILL.md', 'PLAN_REVIEW', 'CODE_REVIEW', 'NEXT SAFE ACTION')
case('ready source route alternatives', '.agents/skills/product-handoff/SKILL.md', 'PASS_THROUGH', 'AMEND_EXISTING', 'CREATE_SPEC', 'только для уже принятого WHAT')
print('PASS: static positive/non-trigger fixtures; live activation NOT RUN')
PY
