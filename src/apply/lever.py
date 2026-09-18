"""Lever's application view, preserving requisition query parameters."""
from urllib.parse import urlsplit,urlunsplit
from ..identity import detect_ats
from .base import Applicator


class LeverApplicator(Applicator):
    ats='lever'

    def can_handle(self,job):
        return detect_ats(job.url)==self.ats

    def application_url(self,job):
        if job.application_url:
            return job.application_url
        p=urlsplit(job.url)
        path=p.path.rstrip('/')
        if not path.endswith('/apply'):
            path+='/apply'
        return urlunsplit((p.scheme,p.netloc,path,p.query,''))
