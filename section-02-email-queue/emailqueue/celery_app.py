from celery import Celery

from emailqueue.settings import QUEUE_NAME, REDIS_URL

app = Celery("emailqueue", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_default_queue=QUEUE_NAME,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # A normal exception still acks, because the task body catches
    # the cases we know about and records them. A SIGKILL never gets
    # that far, so the message stays unacked and comes back.
    task_acks_on_failure_or_timeout=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        # If the worker dies mid-task, Redis redelivers after this.
        "visibility_timeout": 3600,
    },
)

# Imported after `app` exists so the task decorator can bind to it.
import emailqueue.tasks  # noqa: E402,F401
