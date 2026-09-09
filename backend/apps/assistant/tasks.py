from celery import shared_task


@shared_task(soft_time_limit=180, time_limit=210, ignore_result=True)
def answer_question(exchange_id, attempt):
    from apps.assistant.agent import run_exchange
    run_exchange(exchange_id, attempt)
