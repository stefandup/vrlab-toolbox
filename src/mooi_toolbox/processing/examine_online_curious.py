import pandas as pd
import os
from IPython.display import display
import dtale
import datetime

example_file = r"local_data\\responsescuriousMarch.csv"

print(f"Current folder is {os.getcwd()}")

file_path = os.path.join(os.getcwd(), example_file)

if not os.path.exists(file_path):
    print(f"Importing {file_path}")
    print(f"Error {file_path} does not exist!")

df = pd.read_csv(file_path)

df["activity_start_time"] = pd.to_datetime(df["activity_start_time"], unit="ms")
df["activity_end_time"] = pd.to_datetime(df["activity_end_time"], unit="ms")

#df["activity_start_time_dstr"] = df["activity_start_time"].dt.strftime("%Y%m%d %H:%M:%S")

d = dtale.show(df, host="127.0.0.1")
# URL is usually on d; try:
print(getattr(d, '_url', None) or getattr(d, 'main_url', d))

input("Press Enter to close and exit...")  # or: time.sleep(600)