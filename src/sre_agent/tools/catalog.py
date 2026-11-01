from dataclasses import dataclass
from enum import StrEnum

from langchain_core.tools import BaseTool


###############################################
# Класс Категория воздействия
###############################################
# StrEnum создаёт ограниченный набор строковых значений
class ToolCategory(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


###############################################
# Класс Инструмент
###############################################
# Защита frozen=True от случайного изменения метаданных, 
# которая запрещает переназначение полей
@dataclass(frozen=True)
class ToolDefinition:
    tool: BaseTool                  # Исполняемый объект
    category: ToolCategory          # Категория воздействия инструмента
    description: str
    agent: str = "kubernetes"       # Ответственный агент
