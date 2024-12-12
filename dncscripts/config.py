from dncore.configuration.files import FileConfigValues


class ScriptsPluginConfig(FileConfigValues):
    last_args: list[str] = None
    script_path = "./dncscripts.py"
