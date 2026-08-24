from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd
from matplotlib.figure import Figure

from mooi_toolbox.processing.graphomotor_xdf import XdfStream


@dataclass
class GraphomotorTaskResult:
    summary_data: pd.DataFrame = field(default_factory=pd.DataFrame)
    figure_data_out: dict[str, Figure] = field(default_factory=dict)


class GraphomotorTaskProcessor(Protocol):
    task_name: str

    def run(self, streams: list[XdfStream], subject_id: str) -> GraphomotorTaskResult: ...
