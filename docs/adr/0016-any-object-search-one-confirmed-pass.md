# 0016. Any-object search: one confirmed pass per object

Status: accepted

## Context
Search could only find objects that were already indexed. Users ask about anything ("a forklift"), and each new object needs a perception pass over the ready recordings, which costs money.

## Decision
- Search never spends. When a question names an object some ready recordings have no tracks for, the answer carries `needsIndexing` with the object, the recordings and an estimated cost (0.20 dollars per 1,000 frames at 5 fps, at least 50 frames per recording).
- `POST /api/concepts` queues one pass for that object, only when `confirm` is exactly true, after the reply. Asking again while a pass is queued or running returns that pass (one pass per object).
- The spend cap is checked first, counting passes already waiting; if it cannot pay, the answer is 409 `budget_exceeded` and nothing starts.
- `GET /api/concepts/{noun}` reports the pass for polling. Without a key, a pass replays saved results from `demo/sam` and spends nothing; an object with no saved result fails with a fixed message.
- Objects naming a face or an identity (split on spaces, hyphens and apostrophes) are refused (ADR 0008).

## Consequences
The UI shows a "Not searched yet" panel with the cost and a confirm box, polls the pass and reruns the search when it is done. Contract 1.7.0.
