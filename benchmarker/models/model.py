from abc import ABC, abstractmethod

class Model(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str, system: str = "") -> str:
        """returns exactly one answer as text"""
