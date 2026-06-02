# Competency Questions

Graph: `redbot-media-player-cog-architecture`
Scope: RedBot Media Player Cog

## Must answer (P0)

| ID | Type | Question | Query pattern |
|----|------|----------|---------------|
| CQ-01 | SCQ | What entity types exist in this project graph? | List distinct node types |
| CQ-02 | FCQ | What is the root repository node? | Lookup `repo:redbot-media-player-cog` |
| CQ-03 | RCQ | What are the top-level components/modules? | Nodes with `CONTAINS` from repo |
| CQ-04 | RCQ | What configuration artifacts exist? | List nodes where `type=Config` |
| CQ-05 | RCQ | What does this project depend on externally? | Traverse `DEPENDS_ON` from repo/packages |

## Should answer (P1)

| ID | Type | Question | Query pattern |
|----|------|----------|---------------|
| CQ-06 | RCQ | What scripts automate this project? | List nodes where `type=Script` |
| CQ-07 | RCQ | What documentation is indexed? | List nodes where `type=Document` |
| CQ-08 | VCQ | Are all edge endpoints valid? | validate.py pass |

## Verification log

| ID | Status | Notes |
|----|--------|-------|
| CQ-01 | pending | Run queries/query.py |
| CQ-02 | pending | |
| CQ-03 | pending | |
| CQ-04 | pending | |
| CQ-05 | pending | |
| CQ-06 | pending | |
| CQ-07 | pending | |
| CQ-08 | pending | |
