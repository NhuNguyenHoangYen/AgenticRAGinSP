"""Durable ingestion worker. Run separately: python -m src.workers.ingestion."""
import argparse
import asyncio
import hashlib
import signal
import threading
from time import perf_counter
from datetime import timedelta
from uuid import uuid4

from src.api.config import APISettings
from src.document_validation import DocumentValidationError
from src.models.records import DocumentRecord, IngestionJobRecord, utc_now
from src.observability import RequestContext, configure_logging, get_logger, request_context
from src.repositories.mongo import MongoDatabase
from src.repositories.records import Repositories
from src.services.document_ingestion import make_job
from src.services.document_processing import DocumentProcessor
from src.services.rag_pipeline import RAGPipeline, PARSER_VERSION, CHUNKER_VERSION
from src.storage.local_files import LocalFileStorage

log = get_logger(__name__)


class LeaseLost(Exception):
    pass


class IngestionWorker:
    def __init__(self, repositories, storage, pipeline, settings):
        self.repositories, self.storage, self.pipeline, self.settings = repositories, storage, pipeline, settings
        self.worker_id = uuid4().hex
        self.profile = dict(embedding_profile=pipeline.embedding_profile, collection=pipeline.collection,
                            parser_version=PARSER_VERSION, chunker_version=CHUNKER_VERSION)

    async def reconcile(self):
        # Recover API termination between the document and job writes.
        pending = {'status':'uploaded','ingestion_job_id':{'$type':'string'},
                   'index.embedding_profile':self.profile['embedding_profile'],
                   'index.collection':self.profile['collection'],
                   'index.parser_version':self.profile['parser_version'],
                   'index.chunker_version':self.profile['chunker_version']}
        cursor = await self.repositories.documents.collection.aggregate([
            {'$match':pending},
            # let + pipeline form (MongoDB 3.6+). Combining localField/foreignField with a
            # pipeline needs MongoDB 5.0+, which requires AVX; the deployment VM has no AVX.
            {'$lookup':{'from':'chats',
                        'let':{'doc_id':'$_id','owner':'$owner_id'},
                        'pipeline':[{'$match':{'$expr':{'$and':[
                            {'$in':['$$doc_id',{'$ifNull':['$document_ids',[]]}]},
                            {'$eq':['$owner_id','$$owner']}]}}},{'$limit':1}],
                        'as':'attached_chats'}},
            {'$match':{'attached_chats.0':{'$exists':True}}},
            {'$sort':{'updated_at':1}}, {'$limit':100}, {'$project':{'attached_chats':0}},
        ])
        for raw in [item async for item in cursor]:
            document = DocumentRecord.model_validate(raw)
            await self.repositories.jobs.ensure(make_job(document,self.settings))
            await self.repositories.jobs.enable(document.ingestion_job_id,document.owner_id)
        # Complete publication after termination between job success and document-ready writes.
        cursor = self.repositories.jobs.collection.find({**self.profile, 'status': {'$in': ['succeeded','failed']}, 'published': {'$ne': True}}).sort('updated_at', 1).limit(100)
        async for raw in cursor:
            job = IngestionJobRecord.model_validate(raw)
            if await self.repositories.documents.finalize_job(job):
                log.info('ingestion.state_reconciled', job_id=job.id, processed_document_id=job.document_id,
                         status=job.status)
            await self.repositories.jobs.collection.update_one({'_id':job.id,'status':job.status}, {'$set':{'published':True}})
        exhausted = await self.repositories.jobs.exhaust_one(self.profile)
        if exhausted:
            await self.repositories.documents.finalize_job(exhausted)
            log.error('ingestion.attempts_exhausted', job_id=exhausted.id, processed_document_id=exhausted.document_id)

    async def _heartbeat(self, job, done, lost):
        while not done.is_set():
            try:
                await asyncio.wait_for(done.wait(), timeout=self.settings.ingestion_lease_seconds/3)
            except asyncio.TimeoutError:
                try:
                    renewed = await self.repositories.jobs.renew(job, self.settings.ingestion_lease_seconds)
                except Exception:
                    log.exception('worker.lease_renewal_failed', job_id=job.id)
                    lost.set()
                    return
                if not renewed:
                    current = await self.repositories.jobs.get_owned(job.id,job.owner_id)
                    if current and current.status == 'succeeded' and current.lease_token == job.lease_token:
                        return
                    log.warning('worker.lease_lost', job_id=job.id)
                    lost.set()
                    return
                log.debug('worker.lease_renewed', job_id=job.id)

    async def _stage(self, job, stage, document_status=None):
        if not await self.repositories.jobs.leased_update(job, stage=stage):
            raise LeaseLost()
        if document_status and not await self.repositories.documents.attempt_update(job, status=document_status):
            raise LeaseLost()
        job.stage = stage
        log.info('ingestion.stage_started', job_id=job.id, stage=stage, attempt_number=job.attempt)

    async def _process(self, job, lost):
        document = await self.repositories.documents.get_owned(job.document_id, job.owner_id)
        if document is None:
            raise DocumentValidationError('Stored document record is unavailable')
        if not await self.repositories.documents.prepare_attempt(job):
            raise LeaseLost()
        await self._stage(job, 'validation', 'validating')
        content = await asyncio.to_thread(self.storage.read, document.storage_key)
        if hashlib.sha256(content).hexdigest() != document.content_hash:
            raise DocumentValidationError('Stored original content no longer matches its fingerprint')
        parsed = await asyncio.to_thread(DocumentProcessor().parse, content, document.filename)
        await self._stage(job, 'chunking', 'parsing')
        chunks = await asyncio.to_thread(DocumentProcessor().split, parsed.documents)
        if not chunks:
            raise DocumentValidationError('No readable chunks were extracted')
        for position, chunk in enumerate(chunks):
            chunk.metadata.update(owner_id=job.owner_id, document_id=document.id,
                index_version=document.index.index_version,
                chunk_id=f'{document.id}:{document.index.index_version}:{position}', section=f'Chunk {position+1}')
        index = document.index.model_copy(update={'chunk_count':len(chunks)})
        if not await self.repositories.documents.attempt_update(job, index=index.model_dump(mode='python')):
            raise LeaseLost()
        await self._stage(job, 'indexing', 'indexing')
        loop = asyncio.get_running_loop()
        def guard():
            if lost.is_set():
                raise LeaseLost()
        async def report(done, total):
            guard()
            if not await self.repositories.jobs.leased_update(job, completed=done, total=total):
                lost.set()
                raise LeaseLost()
            log.info('indexing.progress', job_id=job.id, completed=done, total=total)
        def progress(done, total):
            asyncio.run_coroutine_threadsafe(report(done,total),loop).result()
        await asyncio.to_thread(self.pipeline.index, chunks, progress, guard)
        guard()
        # Success CAS is the publication fence. A stale worker cannot mark a document ready.
        if not await self.repositories.jobs.leased_update(job, status='succeeded', stage='completed',
            completed=len(chunks), total=len(chunks), error=None, warnings=parsed.warnings,
            completed_at=utc_now(), lease_expires_at=None):
            raise LeaseLost()
        completed = await self.repositories.jobs.get_owned(job.id, job.owner_id)
        await self.repositories.documents.finalize_job(completed)
        await self.repositories.jobs.collection.update_one({'_id':job.id,'status':'succeeded'}, {'$set':{'published':True}})
        log.info('ingestion.completed', job_id=job.id, chunk_count=len(chunks), attempt_number=job.attempt)

    async def _failed(self, job, error):
        permanent = isinstance(error, DocumentValidationError)
        configuration_error = isinstance(error, ValueError) and not permanent
        retry = not (permanent or configuration_error) and job.attempt < job.max_attempts
        delay = min(self.settings.ingestion_retry_seconds * 2**min(job.attempt-1, 8), 300)
        if getattr(error, 'status_code', None) == 429:
            delay = max(delay, 60)
        message = str(error) if isinstance(error, DocumentValidationError) else f'Processing failed during {job.stage}; see server logs'
        status = 'queued' if retry else 'failed'
        changed = await self.repositories.jobs.leased_update(job, status=status, stage=status,
            error=message, non_retryable=permanent, lease_expires_at=None, lease_token=None,
            available_at=utc_now()+timedelta(seconds=delay),
            completed_at=None if retry else utc_now())
        if not changed:
            log.warning('worker.failure_not_committed', job_id=job.id)
            return
        await self.repositories.documents.attempt_update(job,
            status='uploaded' if retry else 'failed', processing_error=message)
        if retry:
            log.warning('ingestion.retry_scheduled', job_id=job.id, delay_seconds=delay, attempt_number=job.attempt)
        else:
            log.error('ingestion.failed', job_id=job.id, permanent=permanent, configuration_error=configuration_error, attempt_number=job.attempt)

    async def run_once(self):
        await self.reconcile()
        job = await self.repositories.jobs.claim(self.profile, self.worker_id, self.settings.ingestion_lease_seconds)
        if job is None:
            return False
        context = RequestContext(user_id=job.owner_id, chat_id=job.chat_id,
            request_id=job.request_id or job.id, ingestion_id=job.id, document_id=job.document_id)
        done, lost = asyncio.Event(), threading.Event()
        with request_context(context):
            log.info('worker.job_claimed', job_id=job.id, worker_id=self.worker_id, attempt_number=job.attempt)
            heartbeat = asyncio.create_task(self._heartbeat(job, done, lost))
            started, outcome = perf_counter(), "succeeded"
            try:
                await asyncio.wait_for(self._process(job,lost), timeout=self.settings.ingestion_timeout_seconds)
            except asyncio.TimeoutError as error:
                outcome = 'timed_out'
                lost.set()  # Stop further provider batches; fence any late result.
                log.exception('worker.job_timed_out', job_id=job.id)
                await self._failed(job,error)
            except LeaseLost:
                outcome = 'lease_lost'
                log.warning('worker.stale_attempt_discarded', job_id=job.id)
            except asyncio.CancelledError:
                outcome = 'interrupted'
                log.warning('worker.attempt_interrupted', job_id=job.id)
                raise  # Lease expiry permits recovery by the next worker.
            except Exception as error:
                outcome = 'failed'
                log.exception('worker.attempt_failed', job_id=job.id)
                if not lost.is_set():
                    await self._failed(job,error)
            finally:
                done.set()
                await heartbeat
                log.info("worker.attempt_finished", job_id=job.id, outcome=outcome,
                         duration_ms=round((perf_counter()-started)*1000,2))
        return True

    async def run(self, stop):
        log.info('worker.started', worker_id=self.worker_id, lease_seconds=self.settings.ingestion_lease_seconds,
                 max_attempts=self.settings.ingestion_max_attempts, **self.profile)
        while not stop.is_set():
            try:
                active = await self.run_once()
            except Exception:
                log.exception('worker.loop_failed', worker_id=self.worker_id)
                active = False
            if not active:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.settings.ingestion_poll_seconds)
                except asyncio.TimeoutError:
                    pass
        log.info('worker.stopped', worker_id=self.worker_id)


async def main(once=False):
    settings=APISettings.from_env()
    configure_logging()
    mongo=MongoDatabase(settings)
    try:
        await mongo.initialize()
        worker=IngestionWorker(Repositories(mongo.database),LocalFileStorage(settings.upload_directory),RAGPipeline(settings),settings)
        stop=asyncio.Event()
        loop=asyncio.get_running_loop()
        for sig in (signal.SIGINT,signal.SIGTERM):
            loop.add_signal_handler(sig,stop.set)
        if once:
            log.info('worker.started', worker_id=worker.worker_id, once=True, **worker.profile)
            await worker.run_once()
            log.info('worker.stopped', worker_id=worker.worker_id, once=True)
        else:
            await worker.run(stop)
    finally:
        await mongo.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true',help='Process at most one available job, then exit')
    asyncio.run(main(parser.parse_args().once))
