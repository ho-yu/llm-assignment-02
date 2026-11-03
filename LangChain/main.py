"""KANT NEXT DevDesk. todo(...)를 필요한 표현이나 코드로 바꿉니다."""
import copy
import json
import sys
import time

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableBranch, RunnableLambda, RunnableParallel, RunnablePassthrough

import support

# 앞 과제의 B2를 가져온다면 정책 지침만 사용합니다. 문서는 context로 전달합니다.
POLICY_INSTRUCTIONS = support.B1_POLICY
POLICY_SOURCE = "B1"


def todo(description):
    """제공: 빈칸을 실행하면 작성할 내용을 알려 줍니다. 이 함수는 수정하지 않습니다."""
    raise NotImplementedError(description)


# 필수 1: 문서 검색
def to_documents(rows, keywords):
    """문서 변환: 본문과 metadata를 나눈 Document를 만듭니다."""
    documents = []
    for row in rows:
        print(f"row : {row}")
        metadata = {key: copy.deepcopy(value) for key, value in row.items() if key != "body"}
        defaults = ["uv", "릴리스", "release"] if row["category"] == "release" else []
        metadata["keywords"] = list(keywords.get(row["doc_id"], defaults))
        # document = todo("문서 변환: row의 body와 metadata로 Document를 만드세요.")
        document = Document({'page_content': row['body'], 'metadata': metadata})
        documents.append(document)
    return documents


def search_documents(query, documents, allowed_ids, top_k=3):
    """키워드 검색: 후보를 제한하고 일치한 키워드 수로 검색합니다."""
    if type(top_k) is not int or not 1 <= top_k <= 3:
        raise ValueError("top_k는 1~3의 정수입니다.")
    normalized = query.casefold()
    allowed = set(allowed_ids)
    scored = []
    for index, document in enumerate(documents):
        # if todo("키워드 검색: 이 문서의 doc_id가 allowed 밖에 있나요?"):
        if document.metadata['doc_id'] not in allowed_ids:
            continue
        words = {word.casefold() for word in document.metadata.get("keywords", []) if word.strip()}
        # score = todo("키워드 검색: words 중 normalized에 포함된 키워드의 개수를 구하세요.")
        score = sum(word for word in words if word in normalized)
        if score > 0:
            scored.append((score, index, document))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:top_k]]


def format_context(documents):
    """제공: 검색 문서를 제목, 출처, 본문으로 표시합니다."""
    if not documents:
        return "검색된 문서가 없습니다."
    return "\n\n".join(
        f'<document id="{doc.metadata["doc_id"]}">\n'
        f'제목: {doc.metadata["title"]}\n출처: {doc.metadata["source_url"]}\n'
        f'{doc.page_content}\n</document>' for doc in documents)


def build_context_chain(documents):
    """검색 입력 연결: 입력 보존과 검색을 병렬로 연결합니다."""
    # 작성 이유: 입력 보존과 검색을 나누는 이유를 한두 줄로 적으세요.
    def retrieve(value):
        query = todo("검색 입력 연결: support.search_query에 question과 history를 전달하세요.")
        return search_documents(query, documents, value["document_ids"])

    def merge(value):
        return {**value["original"], "documents": value["documents"],
                "context": format_context(value["documents"])}

    preserve = RunnablePassthrough().with_config(run_name="preserve_input")
    retrieve_chain = RunnableLambda(retrieve).with_config(run_name="retrieve")
    parallel = todo("검색 입력 연결: original=preserve, documents=retrieve_chain을 RunnableParallel로 묶으세요.")
    return parallel.with_config(run_name="parallel_prepare") | RunnableLambda(merge).with_config(run_name="merge_context")


# 필수 2: 기본 체인
def build_prompt_and_parser():
    """프롬프트와 파서: 답변 형식과 이전 대화 자리를 연결합니다."""
    parser = todo("프롬프트와 파서: support.Answer용 PydanticOutputParser를 만드세요.")
    prompt = ChatPromptTemplate.from_messages([
        ("system", "{policy}\n\n출력 형식:\n{format_instructions}\n\n이번 검색 문서:\n{context}"),
        todo("프롬프트와 파서: history용 MessagesPlaceholder를 넣으세요."),
        ("human", "{question}"),
    ]).partial(policy=POLICY_INSTRUCTIONS, format_instructions=parser.get_format_instructions())
    return prompt.with_config(run_name="prompt"), parser.with_config(run_name="parser")


def validate_sources(answer, documents):
    """출처 검사: 이번에 검색한 문서만 출처로 허용합니다."""
    answer = support.Answer.model_validate(answer)
    allowed = {document.metadata["doc_id"] for document in documents}
    if todo("출처 검사: source_ids에 중복이 있나요?"):
        raise support.SourceValidationError("출처가 중복됩니다.")
    if todo("출처 검사: source_ids에 allowed 밖의 ID가 있나요?"):
        raise support.SourceValidationError("이번 검색 결과에 없는 출처입니다.")
    if todo("출처 검사: 출처가 없는데 needs_human이 false인가요?"):
        raise support.SourceValidationError("근거 없는 답변에는 담당자 확인이 필요합니다.")
    return answer


def build_primary_chain(model):
    """기본 체인 연결: prompt, model, parser와 출처 검사를 연결합니다."""
    prompt, parser = build_prompt_and_parser()
    generate = todo("기본 체인 연결: prompt, model, parser를 순서대로 |로 연결하세요.")

    def finish(value):
        answer = todo("기본 체인 연결: parsed와 documents를 validate_sources로 검사하세요.")
        return {"reply": answer, "route": "primary"}

    return (RunnablePassthrough.assign(parsed=generate.with_config(run_name="generate_parse"))
            | RunnableLambda(finish).with_config(run_name="validate_sources")).with_config(run_name="primary")


def build_answer_chain(model, reliable=False):
    """문서 없음 분기: 문서가 없으면 모델을 호출하지 않습니다."""
    primary = build_primary_chain(model)
    if reliable:
        primary = build_resilient_chain(primary)
    no_documents = RunnableLambda(lambda value: {"reply": support.safe_answer("no_documents"),
                                                "route": "no_documents"})
    def has_no_documents(value):
        return todo("문서 없음 분기: value의 documents가 비어 있는지 확인하세요.")
    return RunnableBranch((has_no_documents, no_documents), primary).with_config(run_name="route_by_documents")


# 필수 3: 대화 이력
def get_history(store, session_id):
    """세션 이력: 세션마다 별도의 이력 객체를 보관합니다."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id는 비어 있지 않은 문자열입니다.")
    if session_id not in store:
        store[session_id] = todo("세션 이력: 새 InMemoryChatMessageHistory를 만드세요.")
    return store[session_id]


def commit_history(store, session_id, question, outcome):
    """이력 저장: 완료된 primary의 질문과 답변만 저장합니다."""
    # 작성 이유: 검색 문서와 대화 이력을 구분하고 primary만 저장하는 이유를 적으세요.
    if todo("이력 저장: outcome의 route가 primary가 아닌가요?"):
        return
    answer = support.Answer.model_validate(outcome["reply"])
    messages = todo("이력 저장: question의 HumanMessage, answer.answer의 AIMessage 순서로 목록을 만드세요.")
    get_history(store, session_id).add_messages(messages)


# 필수 4: 실패 복구
def build_resilient_chain(primary):
    """실패 복구: 허용 오류에만 처음을 포함해 최대 두 번 시도합니다."""
    retry = todo("실패 복구: primary.with_retry에 retry_if_exception_type=support.RECOVERABLE, stop_after_attempt=2, wait_exponential_jitter=False를 적용하세요.")
    fallback = RunnableLambda(lambda value: {"reply": support.safe_answer("fallback"),
                                            "route": "fallback"}).with_config(run_name="fallback")
    return todo("실패 복구: retry.with_fallbacks에 [fallback]과 exceptions_to_handle=support.RECOVERABLE을 연결하세요.")


# 필수 5: 스트리밍
def stream_answer(prepared, model, config=None):
    """청크 전달: 아래 순서대로 청크 전달, 검증과 실패 분기를 채웁니다."""
    # 관측 메모: 실행 기록에서 확인한 실패 단계와 처리 결과를 한두 줄로 적으세요.
    if not prepared["documents"]:
        yield {"type": "final", "reply": support.safe_answer("no_documents").model_dump(), "route": "no_documents"}
        return
    prompt, parser = build_prompt_and_parser()
    stream_chain = prompt | model
    sent_delta = False
    for attempt in range(2):
        iterator = todo("청크 전달: stream_chain.stream에 prepared와 config를 전달하세요.")
        parts = []
        try:
            for chunk in iterator:
                text = support.message_text(chunk)
                if text:
                    parts.append(text)
                    sent_delta = True
                    yield todo("청크 전달: text를 담은 delta 이벤트 dict를 만드세요.")
            parsed = parser.invoke("".join(parts), config=config)
            answer = todo("청크 전달: parsed와 이번 documents로 출처를 검사하세요.")
            yield todo("청크 전달: answer.model_dump()를 담은 final primary 이벤트를 만드세요.")
            return
        except support.RECOVERABLE:
            if todo("실패 처리: 아직 delta를 보내지 않았고 첫 시도인가요?"):
                continue
            if sent_delta:
                yield todo("실패 처리: reason이 unverified_output인 reset 이벤트를 만드세요.")
            yield todo("실패 처리: support.safe_answer('fallback')을 담은 final fallback 이벤트를 만드세요.")
            return
        except Exception:
            if sent_delta:
                yield {"type": "reset", "reason": "execution_error"}
            raise
        finally:
            # 제공: 정상, 실패, 소비 중단 모두에서 하위 스트림을 닫습니다.
            iterator.close()


class TraceHandler(BaseCallbackHandler):
    """실행 기록: 잠금, 상태 보관과 기록 형식은 제공됩니다. 측정할 값만 채웁니다."""
    raise_error = True

    def __init__(self, mode="fixture", path=None, clock=time.perf_counter):
        self.mode = mode
        self.clock = clock
        self.sink = support.TraceSink(path)
        self.records = self.sink.records
        self.active = {}
        self.model_attempts = 0

    def _start(self, kind, run_id, parent_run_id, name):
        with self.sink.lock:
            key = str(run_id)
            state = {"started": todo("실행 기록: self.clock()으로 시작 시각을 읽으세요."),
                     "stage": support.safe_stage(name),
                     "parent_run_id": str(parent_run_id) if parent_run_id else None, "chunk_count": 0}
            self.active[key] = state
            if kind == "model":
                self.model_attempts += 1
            self.sink.write({"event": f"{kind}_start", "stage": state["stage"], "run_id": key,
                             "parent_run_id": state["parent_run_id"], "mode": self.mode,
                             "elapsed_ms": 0.0, "chunk_count": 0, "usage": None, "error_type": None})

    def _finish(self, kind, run_id, error=None, usage=None):
        with self.sink.lock:
            key = str(run_id)
            state = self.active.pop(key, None)
            if state is None:
                return
            elapsed_ms = todo("실행 기록: self.clock()과 state['started']의 차이를 밀리초로 계산하세요.")
            error_type = todo("실행 기록: 오류가 있으면 예외 클래스 이름, 없으면 None을 선택하세요.")
            self.sink.write({"event": f"{kind}_{'error' if error is not None else 'end'}",
                             "stage": state["stage"], "run_id": key,
                             "parent_run_id": state["parent_run_id"], "mode": self.mode,
                             "elapsed_ms": max(0.0, elapsed_ms), "chunk_count": state["chunk_count"],
                             "usage": usage, "error_type": error_type})

    def on_llm_new_token(self, token, *, run_id, parent_run_id=None, **kwargs):
        text = support.message_text(token)
        if not text:
            return
        with self.sink.lock:
            state = self.active.get(str(run_id))
            if state is None:
                return
            state["chunk_count"] = todo("실행 기록: 현재 청크 개수에 이번 텍스트 청크 한 개를 더하세요.")
            self.sink.write({"event": "model_chunk", "stage": state["stage"], "run_id": str(run_id),
                             "parent_run_id": state["parent_run_id"], "mode": self.mode,
                             "elapsed_ms": max(0.0, (self.clock() - state["started"]) * 1000),
                             "chunk_count": state["chunk_count"], "usage": None, "error_type": None})

    # 제공: LangChain 이벤트를 위 세 메서드에 연결합니다.
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        self._start("chain", run_id, parent_run_id, kwargs.get("name", "chain"))

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._finish("chain", run_id)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._finish("chain", run_id, error=error)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._start("model", run_id, parent_run_id, "model")

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._finish("model", run_id, usage=support.extract_usage(response))

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._finish("model", run_id, error=error)


# 선택 심화 1: 초안 검토
def review_draft(draft, documents, reviewer, rewriter):
    """선택 심화: 필수에서 만든 검증을 재사용해 검토, 한 번 수정, 재검토 흐름을 설계합니다."""
    raise NotImplementedError("선택 심화: review_draft를 구현하세요.")


if __name__ == "__main__":
    raise SystemExit(support.main(sys.modules[__name__]))
