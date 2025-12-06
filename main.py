from text2gloss import text_to_asl_gloss
from gloss2pose import gloss_to_video
from dotenv import load_dotenv


def main():
    """Main function to process text to ASL video."""
    # Load environment variables (for API keys)
    load_dotenv()
    
    # Prompt user for input
    print("=" * 60)
    print("ASL Text to Video Converter")
    print("=" * 60)
    user_input = input("\nEnter a sentence to convert to ASL video: ").strip()
    
    if not user_input:
        print("Error: No input provided. Exiting.")
        return
    
    print(f"\nProcessing: '{user_input}'")
    print("-" * 60)
    
    # Step 1: Convert text to ASL gloss
    print("Step 1: Converting text to ASL gloss...")
    try:
        gloss_string = text_to_asl_gloss(user_input)
        print(f"✓ Gloss generated: {gloss_string}")
    except Exception as e:
        print(f"✗ Error converting text to gloss: {e}")
        return
    
    # Step 2: Create gloss dictionary
    gloss_dict = {"Gloss": gloss_string}
    print(f"✓ Gloss dictionary: {gloss_dict}")
    print("-" * 60)
    
    # Step 3: Convert gloss to video
    print("Step 2: Converting gloss to video...")
    try:
        result = gloss_to_video(gloss_string)
        video_path = result.get("SignURL")
        
        if video_path:
            print(f"✓ Video created successfully!")
            print(f"✓ Video file path: {video_path}")
            print("-" * 60)
            print(f"\nFinal result:")
            print(f"  Input text: {user_input}")
            print(f"  ASL Gloss: {gloss_string}")
            print(f"  Video path: {video_path}")
        else:
            print(f"✗ Error: No video file was created")
            print(f"  Result: {result}")
    except Exception as e:
        print(f"✗ Error converting gloss to video: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n" + "=" * 60)
    print("Processing complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
