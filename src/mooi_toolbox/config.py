import tomllib
import os
from functools import lru_cache

@lru_cache
def get_config() -> dict[str,any]:

    with open("pyproject.toml","rb") as f:
        cfg = tomllib.load(f)

    return cfg["tool"]["mooi_toolbox"]

@lru_cache
def get_default_xdf() -> str:

    dft = get_config()
    path_out = os.path.join(
        dft["default_path"],
        f"sub-{dft['default_subject']}",
        f"ses-S{dft['default_session']}",
        dft["default_xdf_folder"],
        (
            f"sub-{dft['default_subject']}"
            f"_ses-S{dft['default_session']}"
            f"_task-{dft['default_xdf_task']}"
            f"_run-001_{dft['default_xdf_folder']}.xdf"
        )
    )
    return path_out

def get_opensignals_eda_data_label() ->str:
    
    dft = get_config()

    return dft["eda_opensignals_data_label"]

def get_biopac_eda_data_label() -> str:
    dft = get_config()

    return dft["eda_biopac_data_label"]

def get_vr_intervals() -> str:
    dft = get_config()
    return dft["vr_intervals"]