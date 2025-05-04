This is a lightweight python/Flask/sqllite application for a creating/tracking a horse race betting pool. 

You can pre-populate the sqllite database with horse information via XLSX (template included form 2025 kentucky derby) 

You can run bet simulations for testing (/betsimulator), takes two arguments, # of people and number of bets per person

You can configure a private event code so when deployed to Heroku or some other host, you have a light layer of security for your event/party -- there is functionality that if the event_code is passed via URL, it will autopopulate the field in the sign-in --> this is perfect for creating a QR code for players to access/sign in easily
THere is a dashboard so players can see who is betting and the totals for WIN/PLACE/SHOW for each horse
there is a /viz endpoint that shows leaderboards and pool totals (good for displaying on a TV) 
