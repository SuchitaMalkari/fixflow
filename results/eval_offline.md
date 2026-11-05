# FixFlow evaluation results

| Metric | dev/v1/offline | dev/v2/offline | test/v1/offline | test/v2/offline |
| --- | --- | --- | --- | --- |
| tickets | 20 | 20 | 30 | 30 |
| category_accuracy_pct | 90.0 | 95.0 | 86.7 | 90.0 |
| team_accuracy_pct | 95.0 | 100.0 | 86.7 | 93.3 |
| action_accuracy_pct | 90.0 | 100.0 | 96.7 | 100.0 |
| urgency_accuracy_pct | 90.0 | 90.0 | 83.3 | 83.3 |
| retrieval_hit@1_pct | 85.0 | 90.0 | 73.3 | 76.7 |
| retrieval_hit@3_pct | 95.0 | 95.0 | 86.7 | 86.7 |
| escalation_precision_pct | 60.0 | 100.0 | 85.7 | 100.0 |
| escalation_recall_pct | 100.0 | 100.0 | 100.0 | 100.0 |
| safety_cases_escalated | 2/2 | 2/2 | 2/2 | 2/2 |
| avg_ms_per_ticket | 0.4 | 0.3 | 0.2 | 0.3 |

## Misses: dev/v1/offline

- `T004` "screen keeps flickering when i scroll in chrome": expected {'action': 'self_serve'}, got {'action': 'escalate'} (confidence 0.24)
- `T011` "Can you install Adobe Illustrator on my machine? I need it for the marketing campaign": expected {'category': 'software', 'action': 'ticket'}, got {'category': 'performance', 'action': 'escalate'} (confidence 0.27)
- `T020` "I just want to talk to a real person about my laptop please": expected {'category': 'boot_os'}, got {'category': 'safety_hazard'} (confidence 0.34)

## Misses: dev/v2/offline

- `T020` "I just want to talk to a real person about my laptop please": expected {'category': 'boot_os'}, got {'category': 'performance'} (confidence 0.25)

## Misses: test/v1/offline

- `T031` "the whole sales team lost wifi in the conference rooms": expected {'category': 'connectivity'}, got {'category': 'account_access'} (confidence 0.55)
- `T032` "VPN says authentication failed even though my password is right": expected {'category': 'connectivity'}, got {'category': 'account_access'} (confidence 0.81)
- `T035` "Excel freezes every time I open a big file and says not responding": expected {'category': 'performance'}, got {'category': 'connectivity'} (confidence 0.35)
- `T044` "Office keeps saying unlicensed product and wants me to activate": expected {'category': 'software', 'action': 'self_serve'}, got {'category': 'connectivity', 'action': 'escalate'} (confidence 0.17)

## Misses: test/v2/offline

- `T032` "VPN says authentication failed even though my password is right": expected {'category': 'connectivity'}, got {'category': 'account_access'} (confidence 0.77)
- `T044` "Office keeps saying unlicensed product and wants me to activate": expected {'category': 'software'}, got {'category': 'boot_os'} (confidence 0.35)
- `T049` "pc not working": expected {'category': 'boot_os'}, got {'category': 'account_access'} (confidence 0.14)

