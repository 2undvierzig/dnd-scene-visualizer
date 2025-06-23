import os
import time
import torch
from diffusers import AutoPipelineForText2Image

token  = os.getenv("your_token")        # export HF_HUB_TOKEN=<read_token> before running
device = "cuda" if torch.cuda.is_available() else "cpu"

t0 = time.perf_counter()
pipe = AutoPipelineForText2Image.from_pretrained(
    "black-forest-labs/FLUX.1-dev",
    torch_dtype=torch.bfloat16,
    token=token,
    trust_remote_code=True
).to(device)
t1 = time.perf_counter()

pipe.load_lora_weights(
    "SouthbayJay/dnd-style-flux",
    weight_name="dnd_style_flux.safetensors",
    token=token
)
t2 = time.perf_counter()

image = pipe("dndstyle illustration of a Barghest").images[0]
t3 = time.perf_counter()

image.save("barghest.png")
t4 = time.perf_counter()

print(f"load_model  : {t1 - t0:.2f} s")
print(f"load_lora   : {t2 - t1:.2f} s")
print(f"inference   : {t3 - t2:.2f} s")
print(f"save_image  : {t4 - t3:.2f} s")
print(f"total       : {t4 - t0:.2f} s")