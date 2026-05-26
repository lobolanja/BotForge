def test_command_modules_import() -> None:
    import forge_bot.commands.invite as invite_module
    from forge_bot.commands.admin_memory import admin_memory, admin_users
    from forge_bot.commands.auth import status
    from forge_bot.commands.auth_guard import admin_required
    from forge_bot.commands.campaign_invite import campaign_invite
    from forge_bot.commands.get_plan import get_plan
    from forge_bot.commands.greet import greet
    from forge_bot.commands.help import help_command
    from forge_bot.commands.ping import ping
    from forge_bot.commands.policy import accept_policy, decline_policy, policy
    from forge_bot.commands.privacy import delete_my_data, memory_clear, privacy
    from forge_bot.commands.set_plan import set_plan
    from forge_bot.commands.time import time
    from forge_bot.commands.translate import translate
    from forge_bot.commands.unknown import unknown_command

    assert hasattr(invite_module, "invite")
    assert callable(greet)
    assert callable(admin_users)
    assert callable(admin_memory)
    assert callable(help_command)
    assert callable(admin_required)
    assert callable(campaign_invite)
    assert callable(get_plan)
    assert callable(ping)
    assert callable(policy)
    assert callable(privacy)
    assert callable(memory_clear)
    assert callable(delete_my_data)
    assert callable(status)
    assert callable(set_plan)
    assert callable(time)
    assert callable(translate)
    assert callable(unknown_command)
    assert callable(accept_policy)
    assert callable(decline_policy)
