def test_command_modules_import() -> None:
    from forge_bot.commands.auth import login, logout, status
    from forge_bot.commands.auth_guard import admin_required, require_login
    from forge_bot.commands.greet import greet
    from forge_bot.commands.help import help_command
    from forge_bot.commands.ping import ping
    from forge_bot.commands.time import time
    from forge_bot.commands.translate import translate
    from forge_bot.commands.unknown import unknown_command

    assert callable(greet)
    assert callable(help_command)
    assert callable(login)
    assert callable(logout)
    assert callable(admin_required)
    assert callable(ping)
    assert callable(require_login)
    assert callable(status)
    assert callable(time)
    assert callable(translate)
    assert callable(unknown_command)
