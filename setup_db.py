from app import app, db, Mesa, Plato
from werkzeug.security import generate_password_hash

with app.app_context():
    print("Limpiando base de datos anterior...")
    db.drop_all()
    db.create_all()

    print("Creando mesas del local...")
    for i in range(1, 6):
        password_mesa = generate_password_hash(f"selva{i}")
        nueva_mesa = Mesa(numero=i, password_hash=password_mesa)
        db.session.add(nueva_mesa)

    print("Creando menú con imágenes...")
    platos_iniciales = [
        Plato(nombre="Tacacho con Cecina", descripcion="Plátano verde majado con manteca y cecina ahumada.", precio=25.00, categoria="Comida", imagen="https://images.unsplash.com/photo-1604908176997-125f25cc6f3d?auto=format&fit=crop&w=300&q=80"),
        Plato(nombre="Juane de Gallina", descripcion="Arroz sazonado con gallina y aceituna en hojas de bijao.", precio=22.00, categoria="Comida", imagen="https://images.unsplash.com/photo-1529059997568-3d847b1154f0?auto=format&fit=crop&w=300&q=80"),
        Plato(nombre="Ceviche de Paiche", descripcion="Paiche en limón selvático con ají charapita.", precio=30.00, categoria="Comida", imagen="https://images.unsplash.com/photo-1534422298391-e4f8c171dd7f?auto=format&fit=crop&w=300&q=80"),
        Plato(nombre="Jarra de Cocona", descripcion="Refrescante jugo natural de cocona helada.", precio=15.00, categoria="Bebida", imagen="https://images.unsplash.com/photo-1622483767028-3f66f32aef97?auto=format&fit=crop&w=300&q=80"),
        Plato(nombre="Refresco de Camu Camu", descripcion="Poderoso antioxidante natural súper helado.", precio=12.00, categoria="Bebida", imagen="https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?auto=format&fit=crop&w=300&q=80")
    ]
    
    db.session.bulk_save_objects(platos_iniciales)
    db.session.commit()
    print("¡Base de datos lista! Se crearon las mesas y el menú fotográfico.")