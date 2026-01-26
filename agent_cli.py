#!/usr/bin/env python3
"""
Instagram Agent CLI - Entry point for running agents.

Usage:
    python agent_cli.py run vera_lx --device emulator-5554
    python agent_cli.py status vera_lx
    python agent_cli.py test-nav --device emulator-5554
"""
import click
import logging
import os
import sys
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("agent_cli")


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
def cli(debug: bool):
    """Instagram Agent CLI"""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)


@cli.command()
@click.argument("agent_name")
@click.option("--device", "-d", default=None, help="ADB device serial")
@click.option("--mongo", default="mongodb://localhost:27017", help="MongoDB URI")
@click.option("--cycles", "-n", default=0, type=int, help="Max cycles (0=unlimited)")
@click.option("--dry-run", is_flag=True, help="Don't execute actions, just log")
def run(agent_name: str, device: str, mongo: str, cycles: int, dry_run: bool):
    """Run an Instagram agent session."""
    click.echo(f"Starting agent: {agent_name}")
    click.echo(f"Device: {device or 'auto-detect'}")
    click.echo(f"MongoDB: {mongo}")
    click.echo(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo("-" * 50)

    try:
        from clickclickclick.agent import Orchestrator
        from clickclickclick.executor.android import AndroidExecutor
        from clickclickclick.config.conf_types import BaseConfig

        # Initialize config
        config = BaseConfig()
        config.models = {
            "finder_config": config.get_config_for_platform("gemini", "finder", "android"),
            "planner_config": config.get_config_for_platform("gemini", "planner", "android"),
        }

        # Initialize orchestrator
        orchestrator = Orchestrator(
            agent_name=agent_name,
            device_serial=device,
            mongo_uri=mongo,
        )

        if not orchestrator.initialize():
            click.echo("Failed to initialize orchestrator", err=True)
            sys.exit(1)

        if not dry_run:
            # Initialize executor
            executor = AndroidExecutor()
            orchestrator.set_executor(executor)

            # Initialize VisionReasoner for LLM-powered engagement
            gemini_api_key = os.environ.get("GEMINI_API_KEY")
            if gemini_api_key:
                gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
                orchestrator.set_reasoner(gemini_api_key, gemini_model)
                click.echo(f"VisionReasoner enabled with model: {gemini_model}")
            else:
                click.echo("GEMINI_API_KEY not set - using fallback heuristics for engagement")

        click.echo(f"Agent initialized. Scheduler status:")
        status = orchestrator.get_status()
        if status.get("scheduler"):
            sched = status["scheduler"]
            click.echo(f"  Activity level: {sched.get('activity_level')}")
            click.echo(f"  Is work shift: {sched.get('is_work_shift')}")
            click.echo(f"  Next window: {sched.get('next_activity_window')}")

        if dry_run:
            click.echo("\n[DRY RUN] Would start session now")
            return

        # Run
        click.echo("\nStarting activity loop...")
        orchestrator.run_loop(max_cycles=cycles)

    except ImportError as e:
        click.echo(f"Import error: {e}", err=True)
        click.echo("Make sure all dependencies are installed", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nInterrupted by user")
    except Exception as e:
        logger.exception("Agent error")
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("agent_name")
@click.option("--mongo", default="mongodb://localhost:27017", help="MongoDB URI")
def status(agent_name: str, mongo: str):
    """Show agent status and statistics."""
    try:
        from clickclickclick.memory.store import MemoryStore

        store = MemoryStore(mongo)
        if not store.connect():
            click.echo("Failed to connect to MongoDB", err=True)
            sys.exit(1)

        summary = store.get_agent_summary(agent_name)

        click.echo(f"Agent: {agent_name}")
        click.echo("-" * 40)

        if summary.get("session_state"):
            state = summary["session_state"]
            click.echo(f"Last active: {state.get('last_active')}")
            click.echo(f"Today's stats:")
            click.echo(f"  Likes: {state.get('likes_today', 0)}")
            click.echo(f"  Comments: {state.get('comments_today', 0)}")
            click.echo(f"  Follows: {state.get('follows_today', 0)}")
            click.echo(f"Total sessions: {state.get('total_sessions', 0)}")
            click.echo(f"Total actions: {state.get('total_actions', 0)}")

            if state.get("cooldown_until"):
                click.echo(f"COOLDOWN until: {state.get('cooldown_until')}")
        else:
            click.echo("No session state found")

        click.echo("\n7-day engagement:")
        stats = summary.get("engagement_7d", {})
        click.echo(f"  Viewed: {stats.get('viewed', 0)}")
        click.echo(f"  Liked: {stats.get('liked', 0)}")
        click.echo(f"  Commented: {stats.get('commented', 0)}")

        click.echo(f"\nKnown obstacles: {summary.get('known_obstacles', 0)}")
        click.echo(f"Total comments sent: {summary.get('total_comments', 0)}")

        store.disconnect()

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("test-nav")
@click.option("--device", "-d", default=None, help="ADB device serial")
def test_nav(device: str):
    """Test navigation module (dump accessibility tree)."""
    click.echo(f"Testing UIAutomator on device: {device or 'auto-detect'}")
    click.echo("-" * 50)

    try:
        from clickclickclick.navigator import UIAutomatorParser

        parser = UIAutomatorParser(device)

        click.echo("Dumping accessibility tree...")
        elements = parser.dump_and_parse()

        click.echo(f"Found {len(elements)} elements")
        click.echo(f"Screen hash: {parser.screen_hash}")

        summary = parser.get_screen_summary()
        click.echo(f"Is Instagram: {summary.get('is_instagram')}")
        click.echo(f"Clickable elements: {summary.get('clickable_elements')}")

        click.echo("\nVisible texts (first 10):")
        for text in summary.get("visible_texts", []):
            click.echo(f"  - {text}")

        # Try to find Instagram elements
        click.echo("\nInstagram elements:")
        for el_type in ["like", "comment", "home_tab", "profile_tab"]:
            el = parser.find_instagram_element(el_type)
            if el:
                click.echo(f"  {el_type}: {el.center}")
            else:
                click.echo(f"  {el_type}: not found")

    except Exception as e:
        logger.exception("Navigation test error")
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("test-actions")
@click.option("--device", "-d", default=None, help="ADB device serial")
@click.option("--action", "-a", default="scroll", help="Action to test: scroll, like, home")
def test_actions(device: str, action: str):
    """Test Instagram actions."""
    click.echo(f"Testing action '{action}' on device: {device or 'auto-detect'}")

    try:
        from clickclickclick.navigator import InstagramActions
        from clickclickclick.executor.android import AndroidExecutor

        executor = AndroidExecutor()
        actions = InstagramActions(executor, device)

        click.echo(f"Executing: {action}")

        if action == "scroll":
            result = actions.scroll_feed()
        elif action == "like":
            result = actions.like_post()
        elif action == "home":
            result = actions.go_home()
        elif action == "profile":
            result = actions.open_profile()
        elif action == "back":
            result = actions.press_back()
        elif action == "dismiss":
            result = actions.dismiss_popup()
        else:
            click.echo(f"Unknown action: {action}")
            return

        click.echo(f"Success: {result.success}")
        click.echo(f"Duration: {result.duration_ms}ms")
        if result.error:
            click.echo(f"Error: {result.error}")
        if result.element:
            click.echo(f"Element: {result.element}")

    except Exception as e:
        logger.exception("Action test error")
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("list-agents")
def list_agents():
    """List available agent configurations."""
    from pathlib import Path

    config_dir = Path(__file__).parent / "clickclickclick" / "config" / "agents"

    if not config_dir.exists():
        click.echo("No agents directory found")
        return

    agents = list(config_dir.glob("*.yaml"))

    if not agents:
        click.echo("No agent configurations found")
        return

    click.echo("Available agents:")
    for agent_path in agents:
        name = agent_path.stem
        click.echo(f"  - {name}")


@cli.command("task")
@click.argument("task_description")
@click.option("--agent", "-a", default="vera_lx", help="Agent persona to use")
@click.option("--device", "-d", default=None, help="ADB device serial")
@click.option("--max-steps", "-n", default=50, type=int, help="Max steps before giving up")
@click.option("--mongo", default="mongodb://localhost:27017", help="MongoDB URI")
def run_task(task_description: str, agent: str, device: str, max_steps: int, mongo: str):
    """
    Execute an autonomous task with LLM navigation.

    Examples:
        python agent_cli.py task "Go to profile vk_artbox, follow if not following, view 3 posts"
        python agent_cli.py task "Scroll home feed for 5 minutes, like interesting posts" --agent vera_lx
    """
    click.echo(f"=== Autonomous Task Execution ===")
    click.echo(f"Task: {task_description}")
    click.echo(f"Agent: {agent}")
    click.echo(f"Device: {device or 'auto-detect'}")
    click.echo(f"Max steps: {max_steps}")
    click.echo(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo("-" * 50)

    # Check API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        click.echo("ERROR: GEMINI_API_KEY not set", err=True)
        sys.exit(1)

    try:
        from clickclickclick.agent import AutonomousAgent
        from clickclickclick.executor.android import AndroidExecutor

        # Initialize executor
        executor = AndroidExecutor()

        # Initialize autonomous agent
        autonomous = AutonomousAgent(
            api_key=api_key,
            executor=executor,
            model_name=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            mongo_uri=mongo,
            device_serial=device,
        )

        # Load persona
        if not autonomous.load_persona(agent):
            click.echo(f"Failed to load persona: {agent}", err=True)
            sys.exit(1)

        click.echo(f"Persona loaded: {agent}")
        click.echo(f"\nStarting task execution...\n")

        # Execute task
        result = autonomous.execute_task(
            task=task_description,
            max_steps=max_steps,
            step_delay=(1.5, 3.0),
        )

        # Show results
        click.echo("\n" + "=" * 50)
        click.echo(f"Task {'COMPLETED' if result.success else 'FAILED'}")
        click.echo(f"Steps taken: {result.steps_taken}")
        click.echo(f"Duration: {result.duration_seconds:.1f}s")

        if result.error:
            click.echo(f"Error: {result.error}")

        if result.posts_viewed:
            click.echo(f"Posts viewed: {len(result.posts_viewed)}")

        if result.comments_made:
            click.echo(f"Comments made: {len(result.comments_made)}")
            for c in result.comments_made:
                click.echo(f"  - {c}")

        click.echo("\nProgress log:")
        for p in result.progress[-15:]:
            click.echo(f"  {p}")

        # Save to MongoDB
        autonomous.save_task_result(result)
        click.echo("\nResult saved to MongoDB")

    except KeyboardInterrupt:
        click.echo("\nInterrupted by user")
    except Exception as e:
        logger.exception("Task error")
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
