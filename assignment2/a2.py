# CMPUT 455 Assignment 2 starter code (PoE2)
# Implement the specified commands to complete the assignment
# Full assignment specification on Canvas

import sys
import signal
import random
import time

class CommandInterface:
    def __init__(self):
        self.command_dict = {
            "help"     : self.help,
            "init_game": self.init_game,
            "show"     : self.show,
            "timelimit": self.timelimit,
            "solve"    : self.solve,
            "score"    : self.score
        }

        # Game state
        self.board = [[None]]
        self.player = 1
        self.handicap = 0.0
        self.score_cutoff = float("inf")
        self.transposition_table = {}
        self.timelimit = 1
        self.start_time = 0
        self.timeout = False

    def process_command(self, s):
        s = s.lower().strip()
        if len(s) == 0:
            return True
        command = s.split(" ")[0]
        args = [x for x in s.split(" ")[1:] if len(x) > 0]
        if command not in self.command_dict:
            print("? Unknown command.\nType 'help' to list known commands.", file=sys.stderr)
            print("= -1\n")
            return False
        try:
            return self.command_dict[command](args)
        except Exception as e:
            print("Command '" + s + "' failed with exception:", file=sys.stderr)
            print(e, file=sys.stderr)
            print("= -1\n")
            return False
        
    def main_loop(self):
        while True:
            s = input()
            if s.split(" ")[0] == "exit":
                print("= 1\n")
                return True
            if self.process_command(s):
                print("= 1\n")

    def help(self, args):
        for command in self.command_dict:
            if command != "help":
                print(command)
        print("exit")
        return True

    def arg_check(self, args, template):
        if len(args) < len(template.split(" ")):
            print("Not enough arguments.\nExpected arguments:", template, file=sys.stderr)
            print("Received arguments: ", end="", file=sys.stderr)
            for a in args:
                print(a, end=" ", file=sys.stderr)
            print(file=sys.stderr)
            return False
        for i, arg in enumerate(args):
            try:
                args[i] = int(arg)
            except ValueError:
                try:
                    args[i] = float(arg)
                except ValueError:
                    print("Argument '" + arg + "' cannot be interpreted as a number.\nExpected arguments:", template, file=sys.stderr)
                    return False
        return True

    def init_game(self, args):
        if len(args) > 4:
            self.board_str = args.pop()
        else:
            self.board_str = ""
        if not self.arg_check(args, "w h p s"):
            return False
        w, h, p, s = args
        if not (1 <= w <= 20 and 1 <= h <= 20):
            print("Invalid board size:", w, h, file=sys.stderr)
            return False
        
        self.width = w
        self.height = h
        self.handicap = p
        if s == 0:
            self.score_cutoff = float("inf")
        else:
            self.score_cutoff = s
        
        self.board = []
        for r in range(self.height):
            self.board.append([0]*self.width)
        self.to_play = 1

        if len(self.board_str) > 0:
            board_rows = self.board_str.split("/")
            if len(board_rows) != self.height:
                print("Board string has wrong height.", file=sys.stderr)
                return False
            
            p1_count = 0
            p2_count = 0
            for y, row_str in enumerate(board_rows):
                if len(row_str) != self.width:
                    print("Board string has wrong width.", file=sys.stderr)
                    return False
                for x, c in enumerate(row_str):
                    if c == "1":
                        self.board[y][x] = 1
                        p1_count += 1
                    elif c == "2":
                        self.board[y][x] = 2
                        p2_count += 1
            
            if p1_count > p2_count:
                self.to_play = 2
            else:
                self.to_play = 1
        
        self.transposition_table.clear()
        return True

    def show(self, args):
        for row in self.board:
            print(" ".join(["_" if v == 0 else str(v) for v in row]))
        return True
    
    def timelimit(self, args):
        if not self.arg_check(args, "s"):
            return False
        self.timelimit = int(args[0])
        return True
    
    def get_moves(self):
        moves = []
        for y in range(self.height):
            for x in range(self.width):
                if self.board[y][x] == 0:
                    moves.append((x, y))
        return moves

    def make_move(self, x, y):
        self.board[y][x] = self.to_play
        self.last_player = self.to_play
        if self.to_play == 1:
            self.to_play = 2
        else:
            self.to_play = 1

    def undo_move(self, x, y):
        self.board[y][x] = 0
        if self.to_play == 1:
            self.to_play = 2
        else:
            self.to_play = 1

    def calculate_score(self):
        p1_score = 0
        p2_score = self.handicap

        for y in range(self.height):
            for x in range(self.width):
                c = self.board[y][x]
                if c != 0:
                    lone_piece = True
                    # Horizontal
                    hl = 1
                    if x == 0 or self.board[y][x-1] != c:
                        x1 = x+1
                        while x1 < self.width and self.board[y][x1] == c:
                            hl += 1
                            x1 += 1
                    else:
                        lone_piece = False
                    # Vertical
                    vl = 1
                    if y == 0 or self.board[y-1][x] != c:
                        y1 = y+1
                        while y1 < self.height and self.board[y1][x] == c:
                            vl += 1
                            y1 += 1
                    else:
                        lone_piece = False
                    # Diagonal
                    dl = 1
                    if y == 0 or x == 0 or self.board[y-1][x-1] != c:
                        x1 = x+1
                        y1 = y+1
                        while x1 < self.width and y1 < self.height and self.board[y1][x1] == c:
                            dl += 1
                            x1 += 1
                            y1 += 1
                    else:
                        lone_piece = False
                    # Anti-diagonal
                    al = 1
                    if y == 0 or x == self.width-1 or self.board[y-1][x+1] != c:
                        x1 = x-1
                        y1 = y+1
                        while x1 >= 0 and y1 < self.height and self.board[y1][x1] == c:
                            al += 1
                            x1 -= 1
                            y1 += 1
                    else:
                        lone_piece = False
                    
                    for line_length in [hl, vl, dl, al]:
                        if line_length > 1:
                            if c == 1:
                                p1_score += 2 ** (line_length-1)
                            else:
                                p2_score += 2 ** (line_length-1)
                    
                    if hl == vl == dl == al == 1 and lone_piece:
                        if c == 1:
                            p1_score += 1
                        else:
                            p2_score += 1

        return p1_score, p2_score
    
    def score(self, args):
        p1, p2 = self.calculate_score()
        print(f"{p1} {p2}")
        return True
    
    def is_terminal(self):
        p1_score, p2_score = self.calculate_score()
        if p1_score >= self.score_cutoff:
            return True, 1
        elif p2_score >= self.score_cutoff:
            return True, 2
        else:
            for y in range(self.height):
                for x in range(self.width):
                    if self.board[y][x] == 0:
                        return False, 0
            if p1_score > p2_score:
                return True, 1
            else:
                return True, 2

    # ---------- A2: Fixed Implementation ----------

    def check_time(self):
        return time.time() - self.start_time > self.timelimit

    def solver_implementation(self):
        self.start_time = time.time()
        self.timeout = False
        
        # Quick terminal check
        is_terminal, winner = self.is_terminal()
        if is_terminal:
            return winner, None
        
        moves = self.get_moves()
        if not moves:
            p1_score, p2_score = self.calculate_score()
            winner = 1 if p1_score > p2_score else 2
            return winner, None

        # Use negamax framework for simpler implementation
        best_move = None
        best_value = -float('inf')
        
        try:
            # Try each move with iterative deepening
            for depth in range(1, min(8, len(moves)) + 1):
                if self.check_time():
                    raise TimeoutError()
                
                current_best_move = None
                current_best_value = -float('inf')
                
                for move in moves:
                    if self.check_time():
                        raise TimeoutError()
                    
                    self.make_move(move[0], move[1])
                    value = -self.negamax(depth-1, -float('inf'), float('inf'))
                    self.undo_move(move[0], move[1])
                    
                    if value > current_best_value:
                        current_best_value = value
                        current_best_move = move
                
                best_move = current_best_move
                best_value = current_best_value
                
                # If we found a guaranteed win, return immediately
                if best_value == float('inf'):
                    return self.to_play, best_move
                # If all moves lead to loss, opponent wins
                elif best_value == -float('inf'):
                    opponent = 2 if self.to_play == 1 else 1
                    return opponent, None
            
            # If we complete search without finding forced win/loss
            if best_value > 0:
                return self.to_play, best_move
            else:
                opponent = 2 if self.to_play == 1 else 1
                return opponent, None
                
        except TimeoutError:
            raise TimeoutError("Search timed out")

    def negamax(self, depth, alpha, beta):
        """Negamax implementation - simpler and more correct"""
        if self.check_time():
            return 0
            
        # Check terminal state
        is_terminal, winner = self.is_terminal()
        if is_terminal:
            if winner == self.to_play:
                return float('inf')
            else:
                return -float('inf')
        
        if depth == 0:
            # Evaluation from current player's perspective
            p1_score, p2_score = self.calculate_score()
            if self.to_play == 1:
                return p1_score - p2_score
            else:
                return p2_score - p1_score
        
        moves = self.get_moves()
        moves = self.move_ordering(moves)
        
        best_value = -float('inf')
        for move in moves:
            self.make_move(move[0], move[1])
            value = -self.negamax(depth-1, -beta, -alpha)
            self.undo_move(move[0], move[1])
            
            if value > best_value:
                best_value = value
            
            if value > alpha:
                alpha = value
            
            if alpha >= beta:
                break
                
        return best_value

    def move_ordering(self, moves):
        center_x, center_y = self.width // 2, self.height // 2
        moves.sort(key=lambda move: abs(move[0] - center_x) + abs(move[1] - center_y)) 
        return moves

    def solve(self, args):
        class TimeoutException(Exception):
            pass
            
        def handler(signum, frame):
            raise TimeoutException("Function timed out.")
        
        # Save state
        original_board = [row[:] for row in self.board]
        original_to_play = self.to_play
        
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(self.timelimit)
            
            winner, winning_move = self.solver_implementation()
            
            # Output format: "winner" or "winner x y"
            if winning_move is not None:
                print(f"{winner} {winning_move[0]} {winning_move[1]}")
            else:
                print(winner)
                
        except (TimeoutException, TimeoutError):
            print("unknown")
        except Exception as e:
            # Restore state on any exception
            self.board = original_board
            self.to_play = original_to_play
            raise e
        finally:
            signal.alarm(0)
            # Always restore original state
            self.board = original_board
            self.to_play = original_to_play

        return True


if __name__ == "__main__":
    interface = CommandInterface()
    interface.main_loop()