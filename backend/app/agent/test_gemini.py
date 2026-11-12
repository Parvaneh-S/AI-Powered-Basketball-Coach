
import os

from dotenv import load_dotenv
from google import genai


# Load API key from the project's .env file
load_dotenv()

MODEL = "gemini-3.5-flash"


def main():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY was not found. "
            "Check your .env file."
        )

    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=(
                "In two sentences, explain why "
                "knee flexion matters in basketball "
                "free throws."
            ),
        )

        print("Model:", MODEL)
        print("\nGemini response:")
        print(response.text)

    finally:
        client.close()


if __name__ == "__main__":
    main()
