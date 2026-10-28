---
type: llm
focus: trace
weight: 1
---

toy.onContainerChange is subscribed before setContainerMode is called, and success is judged from the received state, not from the setContainerMode promise resolving
