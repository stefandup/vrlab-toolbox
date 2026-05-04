import os
from matplotlib.figure import Figure

def save_plot(fig : Figure, results_dir : str, subject_id : str, plot_label : str):
    os.makedirs(results_dir, exist_ok=True)
    out_path = os.path.join(results_dir, f"{subject_id}_{plot_label}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")