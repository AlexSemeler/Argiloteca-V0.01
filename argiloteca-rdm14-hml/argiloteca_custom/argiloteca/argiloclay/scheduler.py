"""Keep native Invenio jobs and bounded local RAG/OpenAlex maintenance."""
from celery.beat import Scheduler,ScheduleEntry
from invenio_jobs.services.scheduler import RunScheduler,JobEntry

KEY='argiloclay-public-metadata'
LOCAL_KEYS=(KEY, 'argiloteca-openalex-recovery')

class ArgiloClayScheduler(RunScheduler):
    def sync(self):
        previous={key:self.entries.get(key) for key in LOCAL_KEYS}
        super().sync()
        for key in LOCAL_KEYS:
            spec=self.app.conf.beat_schedule.get(key)
            if spec:
                # Native periodic DB refresh must not reset the static task clock.
                self.entries[key]=previous[key] or ScheduleEntry(name=key,app=self.app,**spec)

    def reserve(self,entry):
        if isinstance(entry,JobEntry):return super().reserve(entry)
        updated=next(entry);self.entries[entry.name]=updated;return updated

    def apply_entry(self,entry,producer=None):
        if isinstance(entry,JobEntry):return super().apply_entry(entry,producer)
        return Scheduler.apply_entry(self,entry,producer)
