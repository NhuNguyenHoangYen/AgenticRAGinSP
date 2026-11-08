"""Validate source labels and verbatim quotes; semantic entailment is an evaluation concern."""
import json
import re
from typing import Literal

from pydantic import Field,ValidationError

from src.models.records import ValueModel,CitationReference
from src.services.errors import WorkflowError
from src.observability import get_logger

log=get_logger(__name__)


class CitationSelection(ValueModel):
    label:str=Field(pattern=r'^S[1-9][0-9]*$')
    quote:str=Field(min_length=1,max_length=1000)


class CitedAnswer(ValueModel):
    answer:str=Field(min_length=1,max_length=200000)
    answerability:Literal['answerable','partial','unanswerable']
    citations:list[CitationSelection]=Field(max_length=100)


class CitationValidator:
    def validate(self,raw,evidence,scope):
        text=raw.strip()
        if text.startswith('```') and text.endswith('```'):
            lines=text.splitlines()
            if lines[0].strip() in ('```','```json'):text='\n'.join(lines[1:-1])
        try:
            answer=CitedAnswer.model_validate_json(text)
        except (ValidationError,ValueError):
            raise WorkflowError('invalid_answer_format','Model output did not match the cited-answer contract') from None
        registry={item.label:item for item in evidence}
        mentioned=set(re.findall(r'\[(S[0-9]+)\]',answer.answer))
        labels=[item.label for item in answer.citations]
        if len(set(labels))!=len(labels) or mentioned!=set(labels) or any(label not in registry for label in labels):
            raise WorkflowError('invalid_citations','Answer contains unknown, duplicate or mismatched source references')
        normalized=lambda value:re.sub(r'\s+',' ',value).strip()
        citations=[]
        for item in answer.citations:
            source=registry[item.label]
            if normalized(item.quote) not in normalized(source.text):
                raise WorkflowError('invalid_citations','A supporting quote is not present in the supplied excerpt')
            citations.append(CitationReference(**source.model_dump(exclude={'text','truncated'}),quote=item.quote))
        if answer.answerability!='unanswerable' and not citations:
            raise WorkflowError('invalid_citations','A supported or partial answer requires a source citation')
        cited_ids={item.document_id for item in citations}
        if scope.strategy=='comparison' and answer.answerability=='answerable' and cited_ids!={doc.id for doc in scope.documents}:
            raise WorkflowError('incomplete_comparison','A complete comparison must cite evidence from every document in scope')
        log.info('qa.citations_validated',citation_count=len(citations),answerability=answer.answerability)
        return answer,citations
