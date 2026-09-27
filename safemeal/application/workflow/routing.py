from safemeal.application.contracts.workflow.models import WorkflowState


def after_intent(state: WorkflowState) -> str:
    return (
        "direct_reply"
        if state["intent"].kind in {"memory", "clarify", "out_of_scope"}
        else "invoke_agent"
    )
