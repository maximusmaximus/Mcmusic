def stylize_title(title):
    mapping = {
        'A': '\u0394', 'B': '\u0E3F', 'C': '\u03FE', 'D': '\u0110', 'E': '\u0246',
        'F': '\u20A3', 'G': '\u01E4', 'H': '\u2C67', 'I': '\u0142', 'K': '\u049E',
        'L': '\u2C60', 'M': '\u04CE', 'N': '\u20A6', 'O': '\u00D8', 'P': '\u01A4',
        'Q': '\u024B', 'R': '\u01A6', 'S': '\u20A4', 'T': '\u2020', 'U': '\u0244',
        'V': '\u2C74', 'W': '\u20A9', 'X': '\u04FC', 'Y': '\u024E', 'Z': '\u007A'
    }
    result = ''
    for char in title.upper():
        result += mapping.get(char, char)
    return result

if __name__ == '__main__':
    import sys
    print(stylize_title(sys.argv[1]))
