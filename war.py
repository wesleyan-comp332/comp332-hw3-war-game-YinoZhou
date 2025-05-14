"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from enum import Enum
import logging
import random
import socket
import sys
import threading

Game = namedtuple("Game", ["p1", "p2"])
waiting_clients = []
waiting_lock = threading.Lock()

class Command(Enum):
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3

class Result(Enum):
    WIN = 0
    DRAW = 1
    LOSE = 2

def readexactly(sock, numbytes):
    data = bytearray()
    while len(data) < numbytes:
        chunk = sock.recv(numbytes - len(data))
        if not chunk:
            raise Exception("Incomplete read")
        data += chunk
    return bytes(data)

def kill_game(game):
    try:
        game.p1.close()
    except:
        pass
    try:
        game.p2.close()
    except:
        pass

def compare_cards(card1, card2):
    val1 = card1 % 13
    val2 = card2 % 13
    if val1 > val2:
        return 1
    elif val1 < val2:
        return -1
    else:
        return 0

def deal_cards():
    deck = list(range(52))
    random.shuffle(deck)
    return deck[:26], deck[26:]

def handle_game(p1, p2):
    try:
        # Validate WANTGAME commands
        p1_data = readexactly(p1, 2)
        if p1_data[0] != Command.WANTGAME.value or p1_data[1] != 0:
            kill_game(Game(p1, p2))
            return
        p2_data = readexactly(p2, 2)
        if p2_data[0] != Command.WANTGAME.value or p2_data[1] != 0:
            kill_game(Game(p1, p2))
            return

        # Deal cards
        deck1, deck2 = deal_cards()
        p1_cards = list(deck1)
        p2_cards = list(deck2)

        # Send GAMESTART
        p1.send(bytes([Command.GAMESTART.value] + deck1))
        p2.send(bytes([Command.GAMESTART.value] + deck2))

        # Play 26 rounds
        for _ in range(26):
            # Player 1's card
            p1_play = readexactly(p1, 2)
            if p1_play[0] != Command.PLAYCARD.value or p1_play[1] not in p1_cards:
                kill_game(Game(p1, p2))
                return
            p1_cards.remove(p1_play[1])

            # Player 2's card
            p2_play = readexactly(p2, 2)
            if p2_play[0] != Command.PLAYCARD.value or p2_play[1] not in p2_cards:
                kill_game(Game(p1, p2))
                return
            p2_cards.remove(p2_play[1])

            # Compare cards
            res = compare_cards(p1_play[1], p2_play[1])
            if res == 1:
                res_p1, res_p2 = Result.WIN.value, Result.LOSE.value
            elif res == -1:
                res_p1, res_p2 = Result.LOSE.value, Result.WIN.value
            else:
                res_p1 = res_p2 = Result.DRAW.value

            # Send results
            p1.send(bytes([Command.PLAYRESULT.value, res_p1]))
            p2.send(bytes([Command.PLAYRESULT.value, res_p2]))

        # Close connections
        p1.close()
        p2.close()
    except Exception as e:
        logging.error(f"Game error: {e}")
        kill_game(Game(p1, p2))

def serve_game(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen()
        logging.info(f"Server listening on {host}:{port}")
        while True:
            conn, addr = s.accept()
            logging.info(f"New connection: {addr}")
            with waiting_lock:
                waiting_clients.append(conn)
                if len(waiting_clients) >= 2:
                    p1 = waiting_clients.pop(0)
                    p2 = waiting_clients.pop(0)
                    threading.Thread(target=handle_game, args=(p1, p2)).start()


async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)


async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("ConnectionResetError")
        return 0
    except asyncio.IncompleteReadError:
        logging.error("asyncio.streams.ncompleteReadError")
        return 0
    except OSError:
        logging.error("OSError")
        return 0


def main(args):
    """
    launch a client/server
    """
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)

    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]

        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients

        res = loop.run_until_complete(
            asyncio.Task(run_all_clients(), loop=loop))
        logging.info("%d completed clients", res)

    loop.close()


if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])
