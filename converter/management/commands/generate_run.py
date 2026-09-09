from django.core.management.base import BaseCommand

from converter.services.generation import perform_run


class Command(BaseCommand):
    help = "Process one queued generation run. Normally launched by the local application."

    def add_arguments(self, parser):
        parser.add_argument("run_id")
        parser.add_argument("--worker-token")

    def handle(self, *args, **options):
        perform_run(options["run_id"], worker_token=options["worker_token"])
