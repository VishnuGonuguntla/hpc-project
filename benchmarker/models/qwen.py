from models.model import Model
import os
from openai import OpenAI

def get_env_var(name: str) -> str:
    """ Get an environment variable. """
    if name not in os.environ:
        raise ValueError(f"Environment variable {name} not set.")
    return os.environ[name]


class QwenModel(Model):
    def __init__(self, name="qwen/qwen3.8-27b", temperature = 0.2, top_p = 0.95, max_new_tokens=4096):
        self.temperature = temperature
        self.top_p = top_p
        self.name=name
        self.max_new_tokens = max_new_tokens

        api_key = get_env_var("GROQ_API_KEY")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )


    def generate(self, prompt, system = ""):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
    
        completion = self.client.chat.completions.create(
            model=self.name,
            messages=messages,
            max_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            stream=False,
            n=1
        )
        return completion.choices[0].message.content or ""
    