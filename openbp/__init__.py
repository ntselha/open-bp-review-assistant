"""Open BP Review Assistant components.

One module per node of the wire diagram (docs/wire_diagram.md):

    1  validate_input       disposable       readings file -> clean table + rejected rows
    2  flag_implausible     disposable       table -> table + implausible flags
    3  protocol_adherence   atomic protocol  week of valid readings -> adherence record
    4  summary_statistics   disposable       readings -> means, counts, dates
    5  bp_threshold         atomic protocol  means + adherence -> BP category
    6  triage               disposable       adherence + category + recency -> group
                            (decision node)
    7  draft_message        disposable       group + patient fields -> draft text
    8  llm_summary          disposable       patient results JSON -> summary text
                            (prompt) + versioned LLM (atomic)
    9  number_match         disposable       summary + source JSON -> pass/fail,
                                             regenerate once, template fallback
    10 readability_node     atomic protocol  draft text -> FK grade + pass/fail
    11 staff_report         disposable       all results -> HTML report + review sheet

The glue that connects them is run_workflow.py, described in WORKFLOW.md.
"""
