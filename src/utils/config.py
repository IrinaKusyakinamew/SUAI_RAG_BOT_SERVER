import os
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

import yaml  # pyright: ignore[reportMissingModuleSource]

ROOT_PATH = str(Path(__file__).parent.parent)


def set_root_path(path: str):
    global ROOT_PATH
    ROOT_PATH = path  # pyright: ignore[reportConstantRedefinition]


@dataclass
class LoggingConfigGraylog:
    enabled: bool
    host: str
    port: int
    udp: bool


@dataclass
class LoggingConfigGrafana:
    enabled: bool
    url: str
    username: str
    password: str
    labels: dict[str, str]


@dataclass
class LoggingConfigConsole:
    enabled: bool


@dataclass
class LoggingConfig:
    console: LoggingConfigConsole
    graylog: LoggingConfigGraylog
    grafana: LoggingConfigGrafana
    app_name: str
    root_level: str
    levels: dict[str, str]


@dataclass
class ConfigDB:
    host: str
    port: int
    database: str
    username: str
    password: str
    migrations: str


@dataclass
class ConfigTelegram:
    enabled: bool
    bot_token: str
    mode: str  # "polling" или "webhook"


@dataclass
class ConfigGPT:
    api_key: str
    model: str
    base_url: str


@dataclass
class ConfigQdrant:
    host: str
    port: int
    api_key: str


@dataclass
class ConfigEmbeddings:
    model: str
    base_url: str
    api_key: str


@dataclass
class ConfigOpenAI:
    base_url: str
    api_key: str
    proxy: str
    model: str
    max_tokens: int
    temperature: float

    def model_dump(self, exclude: set[str] | None = None) -> dict:
        """Pydantic-like model_dump method for compatibility with src/core code."""
        exclude = exclude or set()
        result = {}
        for field in ["base_url", "api_key", "proxy", "model", "max_tokens", "temperature"]:
            if field not in exclude:
                result[field] = getattr(self, field)
        return result


@dataclass
class ConfigPrompts:
    prompts_dir: str
    system_prompt_file: str


@dataclass
class ConfigExecution:
    logs_dir: str
    reports_dir: str
    max_clarifications: int
    max_iterations: int
    mcp_context_limit: int


@dataclass
class ConfigSearch:
    max_results: int
    tavily_api_key: str
    tavily_api_base_url: str
    max_searches: int
    content_limit: int


@dataclass
class ConfigMCP:
    context_limit: int
    mcpServers: dict


@dataclass
class ConfigScraping:
    content_limit: int


@dataclass
class Config:
    profile: str
    server_host: str
    server_rest_port: int
    logging: LoggingConfig
    db: ConfigDB
    telegram: ConfigTelegram
    gpt: ConfigGPT
    qdrant: ConfigQdrant
    embeddings: ConfigEmbeddings
    openai: ConfigOpenAI
    prompts: ConfigPrompts
    execution: ConfigExecution
    search: ConfigSearch
    mcp: ConfigMCP
    scraping: ConfigScraping
    agents: dict


class ConfigLoader:
    def __init__(self):
        self.configs = []

    def __load_if_exists(self, filename, required=False):
        if os.path.isfile(filename):
            with open(filename, "r") as f:
                yy = yaml.safe_load(f)
                if yy:
                    self.configs.append(yy)
        else:
            if required:
                raise Exception(f"Configuration file {filename} does not exists. Check the working folder.")

    def load_config(self, cls=Config) -> Config:
        profile = os.environ.get("PROFILE", "dev")

        self.__load_if_exists(f"{ROOT_PATH}/config-local.yml")
        self.__load_if_exists("/etc/rag-server/config.yml")
        self.__load_if_exists(f"{ROOT_PATH}/config-{profile}.yml")
        self.__load_if_exists(f"{ROOT_PATH}/config.yml", required=True)

        return self.__create_class_from_values(cls, self.__get_value, "")

    def __get_value_from_yaml(self, data: dict, key: str):
        keys = key.split(".")
        value = data
        for k in keys:
            value = value.get(k)
            if value is None:
                return None
        return value

    def __get_value(self, vname):
        env_name = vname.upper().replace(".", "_")
        if os.getenv(env_name):
            res = os.getenv(env_name)
            if res.isdigit():
                return int(res)
            else:
                return res

        for c in self.configs:
            v = self.__get_value_from_yaml(c, vname)
            if v is not None:
                return v

    def __create_class_from_values(self, cls, get_value_func, outer_name):
        kwargs = {}

        for field in fields(cls):
            if is_dataclass(field.type):
                kwargs[field.name] = self.__create_class_from_values(field.type, get_value_func, f"{outer_name}{field.name}.")
            else:
                # Получаем значение для обычного поля
                fname = f"{outer_name}{field.name}"
                val = get_value_func(fname)
                if val is None:
                    msg = f"Field {fname} is not specified"
                    raise Exception(msg)
                kwargs[field.name] = val

        return cls(**kwargs)


CONFIG: Config = ConfigLoader().load_config(Config)
