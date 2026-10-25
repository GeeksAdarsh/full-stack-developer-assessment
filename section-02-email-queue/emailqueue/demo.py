"""Queue a handful of demo jobs. The worker has to be running already."""

import os

from emailqueue.tasks import send_transactional_email


def main():
    count = int(os.environ.get("DEMO_JOBS", "30"))
    for i in range(count):
        job = {
            "job_id": f"demo-{i}",
            "kind": "order_confirmation",
            "to": f"user{i}@example.com",
        }
        if i == 3:
            job["fail_times"] = 1
        if i == 4:
            job["permanent"] = True
        send_transactional_email.delay(job)
    print(f"Queued {count} jobs on {os.environ.get('EMAIL_QUEUE_NAME', 'emails')}.")
    print("Job 3 fails once, then sends. Job 4 is a bad address and goes to the dead letter.")


if __name__ == "__main__":
    main()
