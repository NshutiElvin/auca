from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/notifications/", consumers.NotificationConsumer.as_asgi()),
]


import string
punctuations= string.punctuation
text="Hello, how was the football match earlier today???"
def find_longest_word(text):
    words_list= text.split(" ")
    longest_idx=None
    longest_word=None
    longest_length=0
    for index, word in words_list:
        clear_word=""
        for c in word:
            if c in punctuations:
                clear_word+=""
            else:
                clear_word+=c
        if not longest_idx and not longest_word and  longest_length==0:
            longest_idx=index
            longest_word=clear_word
            longest_length=len(clear_word)
        else:
            if len(clear_word)>longest_length:
                longest_idx=index
                longest_word=clear_word
                longest_length=len(clear_word)
    return longest_word

print(find_longest_word(text))

        
        
