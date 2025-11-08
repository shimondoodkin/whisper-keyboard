import os
from collections import deque
from textwrap import dedent

from wkey.whisper import groq as groq_provider
from wkey.whisper import openai as openai_provider


DEFAULT_PROMPT = dedent(
    """\
    You are a text correction expert. Fix punctuation, grammar, and typos while keeping the user's intent unchanged.
    Return only the corrected transcript with no extra commentary.
    """
)


def _prompt_template():
    return os.getenv("LLM_CORRECT_PROMPT", DEFAULT_PROMPT).strip() or DEFAULT_PROMPT


def _resolve_llm_runner():
    provider = os.getenv("LLM_CORRECT_PROVIDER", "openai").lower()
    custom_model = os.getenv("LLM_CORRECT_MODEL")

    if provider == "groq":
        model = custom_model or "qwen/qwen3-32b"
        return lambda messages: groq_provider.run_chat_completion(messages, model=model)

    # default to OpenAI
    model = custom_model or "gpt-5-mini"
    return lambda messages: openai_provider.run_chat_completion(messages, model=model)


def create_llm_corrector():
    """
    Creates an LLM text corrector that maintains a history of the last 10 transcripts.
    """
    history = deque(maxlen=10)
    runner = _resolve_llm_runner()

    def corrector(transcript: str) -> str:
        """
        Sends the conversation history and the latest transcript to an LLM for correction.
        """
        if not transcript.strip():
            return transcript

        # The context is the history of previous corrected transcripts.
        context = "".join(history)
        text_to_correct = transcript
        
        instructions = _prompt_template()
        prompt = dedent(
            f"""\
            {instructions}

            Conversation History (most recent first):
            {context}

            Text to Correct:
            {text_to_correct}

            Corrected Text:
            """
        )

        try:
            print("Correcting...")
            corrected_transcript = runner(
                [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ]
            )
            
            # Add the corrected transcript to the history for the next turn's context.
            history.append(corrected_transcript)
            
            return corrected_transcript

        except Exception as e:
            print(f"Error calling LLM API: {e}")
            return transcript  # Return original transcript on error

    return corrector

llm_corrector = create_llm_corrector()
