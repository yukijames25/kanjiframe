      *----------------------------------------------------------------*
      *  顧客マスタ  CUSTMAST   (made-up layout for tests)              *
      *----------------------------------------------------------------*
       01  CUST-REC.
           05  CUST-NO               PIC 9(10).
           05  CUST-KANA             PIC X(30).
           05  CUST-KANJI            PIC N(20).
           05  BIRTH-DATE.
               10  BIRTH-YYYY        PIC 9(4).
               10  BIRTH-MM          PIC 9(2).
               10  BIRTH-DD          PIC 9(2).
           05  BALANCE               PIC S9(13)V99 COMP-3.
           05  CREDIT-LIMIT          PIC S9(9) COMP.
           05  BRANCH-CD             PIC X(3).
           05  ACCT-COUNT            PIC 9(2).
           05  ACCTS OCCURS 3 TIMES.
               10  ACCT-TYPE         PIC X(2).
               10  ACCT-NO           PIC 9(7).
               10  ACCT-BAL          PIC S9(11)V99 COMP-3.
           05  ADDR-AREA             PIC X(60).
           05  ADDR-JP REDEFINES ADDR-AREA.
               10  ADDR-PREF         PIC N(4).
               10  ADDR-REST         PIC N(26).
           05  STATUS-CD             PIC X(1).
               88  ACTIVE            VALUE 'A'.
               88  CLOSED            VALUE 'C'.
           05  FILLER                PIC X(10).
