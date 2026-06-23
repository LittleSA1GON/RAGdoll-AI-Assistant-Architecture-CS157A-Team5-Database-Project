# CS157A-Team5-Database-Project

**Contributors**: Ethan Vu (LittleSA1GON, Team Leader), Geo Lalu (gl91306), Naman Kumar (namank70)

## Prerequsistes
1. MySQL Server (9.7.0)
2. MySQL Workbench (> 8.0.46)
3. Apache Tomcat (> 10.1)
4. Java Development Enviorment (> JDK 25)

## Setup
1. Run MySQL Server
2. Open MySQL Workbench and click File > Run SQL Script, and select `(this directory)/database/schema.sql`, and run it
3. Set DB_PASSWORD to **your sql password** in System Enviorment Variables
4. Open `(tomcat root directory)/conf/catalina/localhost`
5. Create `RAGdoll.xml` and fill it with
```
<Context docBase="(path to this directory)\src\presentation" reloadable="true" />
```
6. Start Tomcat Server