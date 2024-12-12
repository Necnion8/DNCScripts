import asyncio
import inspect
from logging import getLogger
from pathlib import Path

import discord

from dncore import DNCoreAPI
from dncore.command import oncommand, CommandContext
from dncore.plugin import Plugin
from .config import ScriptsPluginConfig

log = getLogger(__name__)


class SilentReturn(Exception):
    pass


def load_function_script(script_path: Path, _globals: dict = None, _locals: dict = None):
    log.debug("Loading script: %s", script_path)
    content = script_path.read_text(encoding="utf8")
    _globals = {} if _globals is None else _globals
    _locals = {} if _locals is None else _locals
    exec(content, _globals, _locals)


def get_dncore_debug_last_messages_field():
    try:
        return DNCoreAPI.default_commands().debug_last_messages
    except Exception as e:
        log.warning(f"Failed to get dncore debug_last_messages list: {e}")
        return []


class ScriptsPlugin(Plugin):
    def __init__(self):
        self.config = ScriptsPluginConfig(self.data_dir / "config.yml")
        self.last_messages = get_dncore_debug_last_messages_field()  # type: list[discord.Message]
        #
        self._shared_data = dict()

    async def on_enable(self):
        self.config.load()

    @oncommand("debugscript", aliases="ds")
    async def cmd_scripts(self, ctx: CommandContext):
        """
        {command}
        {command} (func) [args...]
        > 指定された関数を実行します。省略して前回と同じ関数を実行できます。
        """
        # check file
        script_path = Path(self.config.script_path)
        if not script_path.is_file():
            return await ctx.send_warn(":warning: スクリプトファイルがありません")

        # check args
        if not (args := list(ctx.args or self.config.last_args or [])):
            return await ctx.send_warn(":warning: 実行する関数を指定してください。(前回の引数が保存されていません)")

        self.config.last_args = list(args)
        self.config.save()

        # load script
        _locals = _globals = {"log": log, "ctx": ctx, "__name__": "__main__"}
        try:
            load_function_script(script_path, _globals=_globals, _locals=_locals)
        except Exception as e:
            log.warning("Script Load Error", exc_info=e)
            return await ctx.send_error(f":exclamation: スクリプトを読み込めませんでした: {e}")

        # get function
        func_name = args.pop(0)
        try:
            target_value = _locals[func_name]
        except KeyError:
            return await ctx.send_warn(f":warning: 指定された値が定義されていません: `{func_name}`")

        if not inspect.isfunction(target_value):
            return await ctx.send_warn(f":warning: 指定された値が関数ではありません: "
                                       f"`{func_name}` -> `{repr(target_value)}`")

        # process args
        _args = list()
        _sig_args = list(inspect.signature(target_value).parameters.keys())
        if _sig_args and _sig_args[0] == "ctx":
            _sig_args.pop(0)
            _args.append(ctx)
        if _sig_args and _sig_args[0] == "shared":
            _sig_args.pop(0)
            _args.append(self._shared_data)
        _args.extend(args)

        # execute
        silent = False
        _result = None
        try:
            try:
                if asyncio.iscoroutinefunction(target_value):
                    _result = await target_value(*_args)
                else:
                    _result = target_value(*_args)
            except SilentReturn:
                silent = True

        except Exception as e:
            log.error("Script Execute Error", exc_info=e)
            self.clear_last_messages()
            m = await ctx.send_error(f"{type(e).__name__}: {e}", title="実行エラー", args={})
            self.last_messages.append(m)
            self.last_messages.append(ctx.message)

        else:
            if silent:
                self.clear_last_messages()
            else:
                result = repr(_result)
                log.info("Script Result: %s", result)
                result = result.replace("```", "\\```")
                max_size = 2000 - 9
                if len(result) > max_size:
                    result = "... " + result[len(result) - max_size - 4:]

                self.clear_last_messages()
                if not ctx.self_message:
                    m = await ctx.send_info(
                        f"```py\n{result.replace('{', '{{').replace('}', '}}')}```",
                        title="実行結果",
                        args={}
                    )
                    self.last_messages.append(m)
            self.last_messages.append(ctx.message)

    def clear_last_messages(self):
        for message in self.last_messages:
            DNCoreAPI.run_coroutine(message.delete(), ignores=(discord.HTTPException, ))
        self.last_messages.clear()
