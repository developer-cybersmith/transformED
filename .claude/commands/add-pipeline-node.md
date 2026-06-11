# /add-pipeline-node

Add a new node to the TransformED LangGraph content generation pipeline.

## Usage
`/add-pipeline-node <node-name> <criticality>`

Criticality: `critical` | `optional`

Example: `/add-pipeline-node vocabulary-builder optional`

## What it creates

### Node file: `apps/api/app/modules/content/pipeline/nodes/<node-name>.py`
```python
from app.core.retry import with_retry
from app.modules.content.pipeline.state import PipelineState

# max_attempts=3 for critical, 2 for optional (PRD §14)
@with_retry(max_attempts=<2_or_3>)
async def <node_name>_node(state: PipelineState) -> dict:
    """
    Node: <node-name>
    Criticality: <critical|optional>
    Model: <model from §6.4>
    Cost estimate: ~$X.XX per call
    Output key: '<node_name>_output'
    """
    ...
    return {"<node_name>_output": result}
```

### Prompt file: `apps/api/app/modules/content/pipeline/prompts/<node-name>.py`
Follows the `/gen-prompt` template.

## Steps after creation
1. Add the output key to `PipelineState` TypedDict in `pipeline/state.py`
2. Register the node in `pipeline/graph.py`: `graph.add_node("<node_name>", <node_name>_node)`
3. Add the edge in the correct position in the pipeline order
4. Update checkpoint write in `lesson_jobs.node_outputs`

## Pipeline order reference (PRD §9)
```
extract → structure → chunk → embed →
lesson_planner → slide_generator → summarise_segment → quiz_generator →
segment_complexity → jargon_extractor → intervention_messages →
narration_generator → tts_node → image_generator → package_builder
```
