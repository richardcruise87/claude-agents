#!/usr/bin/env python3
"""
Simple test agent to verify Vertex AI API connectivity.
"""
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    print("Testing Claude Agent SDK with Vertex AI...")
    print("-" * 50)

    try:
        async for message in query(
            prompt="What is 2 + 2? Just give me the answer.",
            options=ClaudeAgentOptions(
                allowed_tools=[],  # No tools needed for this simple test
            ),
        ):
            if hasattr(message, "result"):
                print(f"✓ Success! Agent response:")
                print(f"  {message.result}")
            elif hasattr(message, "text"):
                print(f"  {message.text}")

        print("-" * 50)
        print("✓ Vertex AI API is working correctly!")

    except Exception as e:
        print(f"✗ Error: {e}")
        print("\nPlease check:")
        print("  1. CLAUDE_CODE_USE_VERTEX=1 is set")
        print("  2. Google Cloud credentials are configured (gcloud auth)")
        print("  3. Vertex AI API is enabled in your GCP project")
        return 1

    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
