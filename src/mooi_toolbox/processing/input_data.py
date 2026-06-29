from dataclasses import dataclass

#TODO: Dataclass can be used to also look for the variables and generate errors.
# Define dataclasses to make the input/output contract of the pipeline clear. 
# This will help later in simplifying the larger toolbox strategies used.
# Dataclass is frozen to avoid changes during the pipeline

@dataclass(frozen=True)
class PipelineInput():
    subject_id : str
    biopac_fn: str
    behav_folder : str
    verbose : bool
    show_plots : bool

