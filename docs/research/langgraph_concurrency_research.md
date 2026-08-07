# LangGraph Concurrency & Map-Reduce Research

## Issue
Currently, the `halyk-covenant-agent` project processes scenarios sequentially using `for sc in scenarios:` within LangGraph nodes. This pattern prevents parallel execution and ignores configuration like `MAX_BORROWER_CONCURRENCY`.

## Solution: Map-Reduce via the `Send` API
LangGraph handles dynamic concurrency (fan-out) using the **`Send` API**. Instead of looping through scenarios sequentially inside a node, you define a "router" conditional edge that returns a list of `Send` objects. Each `Send` object dispatches a subset of the state to a target worker node, which LangGraph then executes concurrently in a single "super-step".

### 1. State Management (Reducers)
To aggregate parallel results (fan-in), your graph state must use reducers. If multiple nodes update the same key, a reducer (e.g., `operator.add`) ensures the outputs are appended rather than overwritten, preventing `INVALID_CONCURRENT_GRAPH_UPDATE` errors.

```python
from typing import Annotated, TypedDict
import operator

class GraphState(TypedDict):
    scenarios: list[str]
    # Reducer automatically merges outputs from parallel nodes
    results: Annotated[list[str], operator.add]
```

### 2. Fan-out (Map) Phase
Create a conditional edge or router that maps scenarios to the worker node.

```python
from langgraph.types import Send

def dispatch_scenarios(state: GraphState):
    scenarios = state.get("scenarios", [])
    # Dispatch a Send object for each scenario to run in parallel
    return [Send("process_scenario_node", {"scenario": s}) for s in scenarios]
```

### 3. Worker Node
The worker node receives the specific payload from `Send` and returns an update.

```python
def process_scenario_node(state):
    # state contains the payload passed via Send (e.g., {"scenario": s})
    scenario = state["scenario"]
    # Process scenario
    result = f"Processed {scenario}"
    # The reducer will combine this into the main state's 'results' list
    return {"results": [result]}
```

### 4. Graph Construction
Hook up the map-reduce routing logic. You add conditional edges from the node prior to processing (or START) to the worker node.

```python
from langgraph.graph import StateGraph, START, END

workflow = StateGraph(GraphState)
workflow.add_node("process_scenario_node", process_scenario_node)
# Add conditional edge that uses Send API to fan-out
workflow.add_conditional_edges(START, dispatch_scenarios)
```

## Enforcing Concurrency Limits
To respect the `MAX_BORROWER_CONCURRENCY` limit, LangGraph can throttle execution. When invoking the graph, you pass `max_concurrency` via the config.

```python
config = {"max_concurrency": MAX_BORROWER_CONCURRENCY}
app.invoke(inputs, config=config)
```

## Sources
1. [LangGraph Documentation: Map-Reduce](https://langchain-ai.github.io/langgraph/how-tos/map-reduce/)
2. [LangGraph Send API Reference](https://langchain-ai.github.io/langgraph/reference/types/#langgraph.types.Send)
3. Official LangGraph Guides on dynamic parallel execution and concurrent nodes.
