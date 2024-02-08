rule download_ercot_data:
  output:
    "downloads/ercot_data.pkl"
  cache: True
  shell: "python ./scripts/ercot_data.py"

rule build_model:
  input:
    "downloads/ercot_data.pkl",
    "downloads/fuel_mix_data.pkl"
  shell: "python ./scripts/main.py"

