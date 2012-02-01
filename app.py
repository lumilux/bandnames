from lastfm import API_KEY, API_SECRET
from flask import Flask, jsonify, render_template, abort
import pylast
import redis
from collections import defaultdict
from random import choice

app = Flask(__name__)
#app.debug = True

network = pylast.LastFMNetwork(api_key = API_KEY, api_secret = API_SECRET)
country = network.get_country("United States")

r = redis.Redis(host='localhost', port=6379, db=2)

MUSICD = 'musicd'
ARTISTS = ':artists'
PRE = ':prefix'
MID = ':middle'
SUF = ':suffix'

# DB structure
# musicd: {
#   tag1: {
#     artists: (),
#     prefix: (),
#     middle: (),
#     suffix: () } }
#
# denormalized to redis
# musicd = (tag1, tag2, ...)
# tag1:artists = (...)
# tag1:prefix = (...)
# tag1:middle = (...)
# tag1:suffix = (...)

def build_musicd():
    # get top artists in US
    artists = set()
    top_artists = [a.item.name for a in country.get_top_artists()[:10]]
    artists.update(top_artists)
    more_artists = set(artists)

    # get similar artists from top artists
    for artist in artists:
        if app.debug: print "getting similar artists " + artist

        similar = network.get_artist(artist).get_similar()
        more_artists.update([s.item.name for s in similar])

        if len(more_artists) > 2000:
            break
    
    artists = more_artists

    # get tags of all the fetched artists, and add them to the DB
    for artist in list(artists)[:20]:
        if app.debug: print "adding artist " + artist

        top_tags = network.get_artist(artist).get_top_tags()
        tags = [t.item.name for t in top_tags[:20]]
        for tag in tags:
            if add_tag(tag) and r.sismember(MUSICD, tag):
                r.sadd(tag + ARTISTS, artist)
    
    if app.debug: print "tags: " + str(r.smembers(MUSICD))

def add_tag(tag):
    if app.debug: print "adding tag " + tag
    tag = tag.lower()

    try:
        top_artists = network.get_tag(tag).get_top_artists()
    except:
        return False
    
    if not r.sismember(MUSICD, tag):
        r.sadd(MUSICD, tag)
        
    artist_names = [a.item.name for a in top_artists]
    for a in artist_names:
        r.sadd(tag + ARTISTS, a)
    
    for artist in r.smembers(tag + ARTISTS):
        prefix, middle, suffix = split_name(artist)
        #redis < 2.4 cannot add multiple values per sadd call
        for p in prefix:
            r.sadd(tag + PRE, p)
        for m in middle:
            r.sadd(tag + MID, m)
        for s in suffix:
            r.sadd(tag + SUF, s)
    
    return True

def split_name(name):
    words = name.split(' ')

    if len(words) >= 3:
        return [words[0]], words[1:-1], [words[-1]]

    if len(words) == 2:
        return [words[0]], [], [words[1]]

    if len(words) < 2:
        return [], [], []

def construct_random(prefix, middle, suffix):
    name_sets = {'p': prefix, 'm': middle, 's': suffix}
    name_templates = ['ps', 'ms', 'pms', 'pmms']
    name = ''
    used_words = set()

    #choose random template from name_templates
    template = choice(name_templates)
    for c in template:
        #TODO: get synonyms?
        word_list = list(name_sets[c])
        word = choice(word_list)

        while word in used_words:
            word = choice(word_list)

        used_words.add(word)
        name += word + ' '

    return name

@app.route('/getname/<tag>')
def get_name(tag):
    tag = tag.lower()

    if not r.sismember(MUSICD, tag):
        added = add_tag(tag)

        if not added:
            abort(404)

    prefix = r.smembers(tag + PRE)
    middle = r.smembers(tag + MID)
    suffix = r.smembers(tag + SUF)
    res = construct_random(prefix, middle, suffix)

    return jsonify({'result': res})

@app.route('/')
def index():
    return render_template('base.html')

if not r.exists(MUSICD):
    if app.debug: print "building musicd"
    build_musicd()

if __name__ == '__main__':
    app.run()