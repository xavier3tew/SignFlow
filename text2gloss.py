from groq import Groq
import os

from dotenv import load_dotenv

def construct_query(text):
    return f"""

Human: Here are some examples of translations from english text to ASL gloss 
Examples:
Apples ==> APPLE
you  ==> IX-2P
your  ==> IX-2P
Love ==> LIKE
My ==> IX-1P
Thanks ==> THANK-YOU
am ==> 
and ==> 
be ==>
of ==>
video ==> MOVIE
image ==> PICTURE
conversations ==> TALK
type of ==> TYPE
? ==> QUESTION
Watch ==> SEE

Translate the following english text to ASL Gloss and surround it  with tags <gloss> and </gloss>.
{text} ==>


Assistant:"""


def text_to_asl_gloss(text):
    """Convert English text to ASL Gloss using Groq (Claude model)
    
    Parameters
    ----------
    text: str, required
        Input English text to convert to ASL Gloss
        
    Returns
    ------
    str: ASL Gloss translation
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    
    # create the prompt
    prompt_data = construct_query(text)
    
    # Use Claude model via Groq with same settings as before
    model = "llama-3.1-8b-instant"
    
    message = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt_data
            }
        ],
        max_tokens=3000,
        temperature=0.1,
        top_p=0.5
    )
    
    output_text = message.choices[0].message.content
    
    sub1 = '<gloss>'
    sub2 = '</gloss>'
    idx1 = output_text.find(sub1)
    idx2 = output_text.find(sub2)
    # length of substring 1 is added to
    # get string from next character
    gloss = output_text[idx1 + len(sub1) + 1: idx2]
    print("this is executed")
    print(gloss)
    return gloss


if __name__ == "__main__":
    load_dotenv()
    text_to_asl_gloss("Hello how are you doing")
    text_to_asl_gloss("How are you?")
    text_to_asl_gloss("She is watching a movie")
    text_to_asl_gloss("He wants to play")
    text_to_asl_gloss("Can you come with me?")
