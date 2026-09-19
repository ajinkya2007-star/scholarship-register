PRIVATE REGISTRATION SETUP
==========================

1. Open Terminal and go into this folder.
2. Install the one dependency:
   python3 -m pip install -r requirements.txt

3. Start the private server:
   python3 server.py

4. Open this in Safari:
   http://127.0.0.1:8000/

5. When someone creates an account, the server adds the registration to:
   registrations.xlsx

PRIVACY
-------
- registrations.xlsx is kept on this computer beside server.py.
- The website never displays the workbook.
- The HTTP server deliberately does not serve registrations.xlsx or a
  directory listing.
- The password is NOT written to the Excel sheet.
- The certificate filename is recorded, not the certificate file itself.

IMPORTANT
---------
This is private storage on the computer running server.py. If you deploy the
HTML to a public hosting service, you must deploy the server/API too; opening
the HTML directly as file:// will not save registrations to Excel.
